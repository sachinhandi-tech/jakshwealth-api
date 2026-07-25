"""
query.dsl_compiler

Compiles a predictable Custom JSON DSL into parameterized SQL for Postgres and
Databricks SQL.

===========================================================================
WHY THIS DSL EXISTS
===========================================================================

This library is designed for interactive reporting / AI-assisted querying.

Instead of letting a UI or LLM generate raw SQL directly, it generates a
predictable JSON DSL which is then compiled into SQL safely.

Goals:
1) LLM-friendly and predictable
2) Capable enough for real reporting use-cases
3) Safe-by-default (parameterized values, identifier validation)
4) Portable across Postgres and Databricks SQL

===========================================================================
SUPPORTED CAPABILITIES
===========================================================================

- FROM + JOINs
- Targeted selection
  - fields
  - aliases
  - literals
  - functions
  - aggregates
  - CASE expressions
- WHERE / HAVING filters
  - nested and/or/not
  - comparison operators
  - string operators
  - null checks
  - between / in
- GROUP BY
- Window / ranking functions
  - row_number
  - rank
  - dense_rank
  - ntile
  - lag
  - lead
  - first_value
  - last_value
- ORDER BY
- DISTINCT
- LIMIT / OFFSET
- QUALIFY (Databricks only)
- Optional metadata-based allowlist validation

===========================================================================
CANONICAL DSL SHAPE
===========================================================================

{
  "from": { "table": "claims", "alias": "c" },

  "joins": [
    {
      "type": "left",
      "table": "members",
      "alias": "m",
      "on": {
        "left": "c.member_id",
        "op": "eq",
        "right": "m.member_id"
      }
    }
  ],

  "select": [
    { "field": "c.claim_id", "as": "claim_id" },
    { "field": "m.member_name", "as": "member_name" },
    { "agg": "sum", "field": "c.paid_amount", "as": "total_paid" },
    {
      "window_fn": "dense_rank",
      "partition_by": ["m.region"],
      "order_by": [{ "field": "c.paid_amount", "dir": "desc" }],
      "as": "region_paid_rank"
    }
  ],

  "where": {
    "and": [
      { "field": "c.claim_status", "op": "in", "value": ["PAID", "DENIED"] },
      { "field": "c.service_date", "op": "between", "value": ["2026-01-01", "2026-03-31"] },
      {
        "or": [
          { "field": "m.member_name", "op": "contains", "value": "smith" },
          { "field": "m.region", "op": "eq", "value": "South" }
        ]
      }
    ]
  },

  "group_by": ["m.region", "c.claim_status"],

  "having": {
    "and": [
      { "left": { "agg": "sum", "field": "c.paid_amount" }, "op": "gte", "right": 10000 }
    ]
  },

  "order_by": [
    { "field": "m.region", "dir": "asc" },
    { "field": "total_paid", "kind": "alias", "dir": "desc" }
  ],

  "limit": 100,
  "offset": 0
}

===========================================================================
PREDICTABLE EXPRESSION FORMS
===========================================================================

1) Field reference
   "c.claim_id"
   { "field": "c.claim_id" }

2) Literal
   { "literal": 123 }
   { "literal": "PAID" }

3) Aggregate
   { "agg": "sum", "field": "c.paid_amount", "as": "total_paid" }
   { "agg": "count", "field": "*", "as": "row_count" }
   { "agg": "count", "field": "c.claim_id", "distinct": true, "as": "distinct_claims" }

4) Function
   { "func": "coalesce", "args": ["m.member_name", { "literal": "UNKNOWN" }] }

5) Window / ranking function
   {
     "window_fn": "row_number",
     "partition_by": ["m.region"],
     "order_by": [{ "field": "c.paid_amount", "dir": "desc" }],
     "as": "rn"
   }

6) CASE
   {
     "case": [
       {
         "when": { "field": "c.paid_amount", "op": "gte", "value": 1000 },
         "then": { "literal": "HIGH" }
       },
       {
         "when": { "field": "c.paid_amount", "op": "gte", "value": 500 },
         "then": { "literal": "MEDIUM" }
       }
     ],
     "else": { "literal": "LOW" },
     "as": "paid_band"
   }

===========================================================================
PREDICTABLE PREDICATE FORMS
===========================================================================

1) Field/value filter
   { "field": "c.claim_status", "op": "eq", "value": "PAID" }

2) Column-to-column comparison
   { "left": "c.member_id", "op": "eq", "right": "m.member_id" }

3) Boolean containers
   { "and": [ ... ] }
   { "or": [ ... ] }
   { "not": { ... } }

===========================================================================
SUPPORTED OPERATORS
===========================================================================

Comparison:
- eq, ne, gt, gte, lt, lte

Set / range:
- in, not_in, between

String:
- like, ilike, starts_with, ends_with, contains

Null:
- is_null, is_not_null

===========================================================================
METADATA (OPTIONAL BUT RECOMMENDED)
===========================================================================

metadata = {
  "tables": {
    "claims": {
      "columns": ["claim_id", "member_id", "claim_status", "service_date", "paid_amount"]
    },
    "members": {
      "columns": ["member_id", "member_name", "region"]
    }
  }
}

Pass metadata to SqlCompiler(...) or compile_json_dsl(...).

===========================================================================
EXAMPLE USAGE
===========================================================================

from query.dsl_compiler import compile_json_dsl

compiled = compile_json_dsl(dsl, dialect="postgres", metadata=metadata)
print(compiled.sql)
print(compiled.params)

For Databricks:
compiled = compile_json_dsl(dsl, dialect="databricks", metadata=metadata)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import json
import re

JSON = Dict[str, Any]


class DSLValidationError(ValueError):
    """Raised when the JSON DSL is invalid."""


@dataclass
class CompiledQuery:
    sql: str
    params: List[Any]
    dialect: str


class _IdentifierPolicy:
    """
    Strict validation for SQL identifiers to keep generated SQL predictable.
    We only allow unquoted simple identifiers: letters, numbers, underscore,
    and must begin with letter or underscore.
    """

    _IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    @classmethod
    def validate_identifier(cls, part: str, kind: str = "identifier") -> str:
        if not isinstance(part, str) or not cls._IDENT_RE.match(part):
            raise DSLValidationError(f"Invalid {kind}: {part!r}")
        return part

    @classmethod
    def split_qualified(cls, ref: str) -> Tuple[Optional[str], str]:
        """
        Supports:
          field
          alias.field
        """
        if not isinstance(ref, str) or not ref:
            raise DSLValidationError(f"Invalid field reference: {ref!r}")

        pieces = ref.split(".")
        if len(pieces) == 1:
            alias = None
            field = pieces[0]
        elif len(pieces) == 2:
            alias, field = pieces
            cls.validate_identifier(alias, "table alias")
        else:
            raise DSLValidationError(
                f"Field references must be 'field' or 'alias.field': {ref!r}"
            )

        cls.validate_identifier(field, "field")
        return alias, field

    @classmethod
    def is_qualified_ref(cls, ref: str) -> bool:
        """
        Returns True only for alias.field.
        This helps avoid mistaking plain string literals like 'PAID'
        for column references.
        """
        if not isinstance(ref, str):
            return False
        pieces = ref.split(".")
        if len(pieces) != 2:
            return False
        try:
            cls.validate_identifier(pieces[0], "table alias")
            cls.validate_identifier(pieces[1], "field")
            return True
        except DSLValidationError:
            return False


class _Dialect:
    name = "generic"

    def quote_ident(self, identifier: str) -> str:
        raise NotImplementedError

    def placeholder(self, index: int) -> str:
        raise NotImplementedError

    def render_ilike(self, left_sql: str, right_sql: str) -> str:
        raise NotImplementedError

    def render_limit_offset(self, limit: Optional[int], offset: Optional[int]) -> str:
        parts: List[str] = []
        if limit is not None:
            parts.append(f"LIMIT {int(limit)}")
        if offset is not None:
            parts.append(f"OFFSET {int(offset)}")
        return " ".join(parts)


class PostgresDialect(_Dialect):
    name = "postgres"

    def quote_ident(self, identifier: str) -> str:
        _IdentifierPolicy.validate_identifier(identifier)
        return f'"{identifier}"'

    def placeholder(self, index: int) -> str:
        return "%s"

    def render_ilike(self, left_sql: str, right_sql: str) -> str:
        return f"{left_sql} ILIKE {right_sql}"


class DatabricksDialect(_Dialect):
    name = "databricks"

    def quote_ident(self, identifier: str) -> str:
        _IdentifierPolicy.validate_identifier(identifier)
        return f"`{identifier}`"

    def placeholder(self, index: int) -> str:
        return "?"

    def render_ilike(self, left_sql: str, right_sql: str) -> str:
        # LOWER(...) LIKE LOWER(...) for cross-compatibility.
        return f"LOWER({left_sql}) LIKE LOWER({right_sql})"


class SqlCompiler:
    """
    Compiles a predictable Custom JSON DSL into parameterized SQL.

    Parameters
    ----------
    dialect:
        'postgres' or 'databricks'

    metadata:
        Optional allowlist metadata:
        {
          "tables": {
            "claims": {"columns": ["claim_id", "member_id", ...]},
            "members": {"columns": ["member_id", "member_name", ...]}
          }
        }

    strict_alias_resolution:
        If True, any alias.field reference must use a known FROM/JOIN alias.

    quote_aliases:
        If True, aliases themselves are quoted in SQL output.
    """

    _JOIN_TYPES = {"inner", "left", "right", "full", "cross"}
    _ORDER_DIRS = {"asc", "desc"}
    _NULLS_POS = {"first", "last"}
    _AGGS = {"count", "sum", "avg", "min", "max"}
    _WINDOW_FNS = {
        "row_number",
        "rank",
        "dense_rank",
        "ntile",
        "lag",
        "lead",
        "first_value",
        "last_value",
    }
    _PREDICATE_OPS = {
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "between",
        "like",
        "ilike",
        "starts_with",
        "ends_with",
        "contains",
        "is_null",
        "is_not_null",
    }

    def __init__(
        self,
        dialect: str = "postgres",
        metadata: Optional[JSON] = None,
        strict_alias_resolution: bool = True,
        quote_aliases: bool = False,
    ) -> None:
        dialect = (dialect or "postgres").lower()
        if dialect == "postgres":
            self.dialect: _Dialect = PostgresDialect()
        elif dialect == "databricks":
            self.dialect = DatabricksDialect()
        else:
            raise DSLValidationError(f"Unsupported dialect: {dialect!r}")

        self.metadata = metadata or {}
        self.strict_alias_resolution = strict_alias_resolution
        self.quote_aliases = quote_aliases

        self._params: List[Any] = []
        self._aliases: Dict[str, str] = {}
        self._select_aliases: set[str] = set()
        self._known_tables: Dict[str, Sequence[str]] = {}

        for tname, meta in (self.metadata.get("tables") or {}).items():
            _IdentifierPolicy.validate_identifier(tname, "table")
            cols = meta.get("columns", []) if isinstance(meta, dict) else []
            cleaned: List[str] = []
            for c in cols:
                _IdentifierPolicy.validate_identifier(c, "column")
                cleaned.append(c)
            self._known_tables[tname] = cleaned

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def compile(self, dsl: JSON) -> CompiledQuery:
        self._reset()

        if not isinstance(dsl, dict):
            raise DSLValidationError("DSL root must be an object/dict")

        from_obj = dsl.get("from")
        if not isinstance(from_obj, dict):
            raise DSLValidationError(
                "'from' must be an object like {'table': 'x', 'alias': 't'}"
            )

        from_sql = self._compile_from(from_obj)
        joins_sql = self._compile_joins(dsl.get("joins", []))
        select_sql = self._compile_select_clause(
            dsl.get("select", []),
            bool(dsl.get("distinct"))
        )
        where_sql = self._compile_where_like(dsl.get("where"), "WHERE")
        group_by_sql = self._compile_group_by(dsl.get("group_by", []))
        having_sql = self._compile_where_like(dsl.get("having"), "HAVING")
        qualify_sql = self._compile_qualify(dsl.get("qualify"))
        order_by_sql = self._compile_order_by(dsl.get("order_by", []))
        page_sql = self._compile_limit_offset(dsl.get("limit"), dsl.get("offset"))

        sql_parts: List[str] = [select_sql, f"FROM {from_sql}"]

        if joins_sql:
            sql_parts.append(joins_sql)
        if where_sql:
            sql_parts.append(where_sql)
        if group_by_sql:
            sql_parts.append(group_by_sql)
        if having_sql:
            sql_parts.append(having_sql)
        if qualify_sql:
            sql_parts.append(qualify_sql)
        if order_by_sql:
            sql_parts.append(order_by_sql)
        if page_sql:
            sql_parts.append(page_sql)

        sql = "\n".join(sql_parts)
        return CompiledQuery(sql=sql, params=list(self._params), dialect=self.dialect.name)

    # ---------------------------------------------------------------------
    # State reset
    # ---------------------------------------------------------------------

    def _reset(self) -> None:
        self._params = []
        self._aliases = {}
        self._select_aliases = set()

    # ---------------------------------------------------------------------
    # Validation helpers
    # ---------------------------------------------------------------------

    def _validate_table_known(self, table: str) -> None:
        if self._known_tables and table not in self._known_tables:
            raise DSLValidationError(f"Unknown table in metadata allowlist: {table!r}")

    def _validate_column_known(self, table: str, column: str) -> None:
        columns = self._known_tables.get(table)
        if columns and column not in columns:
            raise DSLValidationError(f"Unknown column {table}.{column} in metadata allowlist")

    def _register_alias(self, alias: str, table: str) -> None:
        if alias in self._aliases:
            raise DSLValidationError(f"Duplicate alias: {alias!r}")
        self._aliases[alias] = table

    def _render_alias(self, alias: str) -> str:
        _IdentifierPolicy.validate_identifier(alias, "alias")
        return self.dialect.quote_ident(alias) if self.quote_aliases else alias

    def _compile_table_ref(self, table: str) -> str:
        _IdentifierPolicy.validate_identifier(table, "table")
        self._validate_table_known(table)
        return self.dialect.quote_ident(table)

    def _compile_column_ref(self, ref: str, allow_aliasless: bool = True) -> str:
        alias, field = _IdentifierPolicy.split_qualified(ref)

        if alias is None:
            if not allow_aliasless:
                raise DSLValidationError(f"Alias required for field reference: {ref!r}")
            return self.dialect.quote_ident(field)

        if self.strict_alias_resolution and alias not in self._aliases:
            raise DSLValidationError(f"Unknown alias in field reference: {ref!r}")

        table = self._aliases.get(alias)
        if table:
            self._validate_column_known(table, field)

        return f"{self._render_alias(alias)}.{self.dialect.quote_ident(field)}"

    def _bind(self, value: Any) -> str:
        self._params.append(value)
        return self.dialect.placeholder(len(self._params))

    # ---------------------------------------------------------------------
    # FROM / JOIN
    # ---------------------------------------------------------------------

    def _compile_from(self, obj: JSON) -> str:
        table = obj.get("table")
        alias = obj.get("alias")

        if not isinstance(table, str):
            raise DSLValidationError("from.table is required and must be a string")
        if not isinstance(alias, str):
            raise DSLValidationError("from.alias is required and must be a string")

        _IdentifierPolicy.validate_identifier(alias, "alias")
        table_sql = self._compile_table_ref(table)
        self._register_alias(alias, table)

        return f"{table_sql} AS {self._render_alias(alias)}"

    def _compile_joins(self, joins: Any) -> str:
        if not joins:
            return ""

        if not isinstance(joins, list):
            raise DSLValidationError("joins must be a list")

        out: List[str] = []

        for j in joins:
            if not isinstance(j, dict):
                raise DSLValidationError("Each join must be an object")

            jtype = str(j.get("type", "inner")).lower()
            if jtype not in self._JOIN_TYPES:
                raise DSLValidationError(f"Unsupported join type: {jtype!r}")

            table = j.get("table")
            alias = j.get("alias")

            if not isinstance(table, str) or not isinstance(alias, str):
                raise DSLValidationError("Each join requires table and alias strings")

            _IdentifierPolicy.validate_identifier(alias, "alias")

            join_sql = (
                f"{jtype.upper()} JOIN {self._compile_table_ref(table)} AS {self._render_alias(alias)}"
            )

            self._register_alias(alias, table)

            if jtype != "cross":
                on_expr = j.get("on")
                if on_expr is None:
                    raise DSLValidationError("Non-cross joins require 'on'")
                on_sql = self._compile_condition(on_expr)
                join_sql += f" ON {on_sql}"

            out.append(join_sql)

        return "\n".join(out)

    # ---------------------------------------------------------------------
    # SELECT
    # ---------------------------------------------------------------------

    def _compile_select_clause(self, select_items: Any, distinct: bool) -> str:
        if not select_items or not isinstance(select_items, list):
            raise DSLValidationError("select must be a non-empty list")

        rendered: List[str] = []
        for item in select_items:
            expr_sql, alias = self._compile_select_item(item)
            if alias:
                self._select_aliases.add(alias)
                rendered.append(f"  {expr_sql} AS {self.dialect.quote_ident(alias)}")
            else:
                rendered.append(f"  {expr_sql}")

        distinct_sql = "DISTINCT " if distinct else ""
        return f"SELECT {distinct_sql}\n" + ",\n".join(rendered)

    def _compile_select_item(self, item: Any) -> Tuple[str, Optional[str]]:
        if isinstance(item, str):
            return self._compile_expr(item), None

        if not isinstance(item, dict):
            raise DSLValidationError("Each select item must be a string or object")

        alias = item.get("as")
        if alias is not None:
            _IdentifierPolicy.validate_identifier(alias, "select alias")

        if "field" in item and set(item.keys()).issubset({"field", "as", "kind"}):
            return self._compile_field_or_alias(item["field"], item.get("kind")), alias

        return self._compile_expr(item), alias

    # ---------------------------------------------------------------------
    # Expressions
    # ---------------------------------------------------------------------

    def _compile_expr(self, expr: Any) -> str:
        if isinstance(expr, str):
            return self._compile_column_ref(expr)

        if not isinstance(expr, dict):
            return self._bind(expr)

        if "field" in expr and set(expr.keys()).issubset({"field", "kind", "as"}):
            return self._compile_field_or_alias(expr["field"], expr.get("kind"))

        if "literal" in expr:
            return self._bind(expr["literal"])

        if "agg" in expr:
            return self._compile_aggregate(expr)

        if "func" in expr:
            return self._compile_function(expr)

        if "window_fn" in expr:
            return self._compile_window(expr)

        if "case" in expr:
            return self._compile_case(expr)

        if "raw_alias" in expr:
            alias = expr["raw_alias"]
            _IdentifierPolicy.validate_identifier(alias, "alias reference")
            return self.dialect.quote_ident(alias)

        raise DSLValidationError(f"Unsupported expression object: {expr}")

    def _compile_field_or_alias(self, value: Any, kind: Optional[str]) -> str:
        if not isinstance(value, str):
            raise DSLValidationError("field must be a string")

        if kind == "alias":
            _IdentifierPolicy.validate_identifier(value, "alias reference")
            return self.dialect.quote_ident(value)

        if value == "*":
            return "*"

        return self._compile_column_ref(value)

    def _compile_aggregate(self, expr: JSON) -> str:
        fn = str(expr.get("agg", "")).lower()
        if fn not in self._AGGS:
            raise DSLValidationError(f"Unsupported aggregate: {fn!r}")

        field = expr.get("field", "*")
        distinct = bool(expr.get("distinct"))

        if field == "*":
            inner = "*"
            if distinct:
                raise DSLValidationError("distinct is not valid with aggregate field='*'")
        else:
            inner = self._compile_expr({"field": field} if isinstance(field, str) else field)

        distinct_sql = "DISTINCT " if distinct else ""
        return f"{fn.upper()}({distinct_sql}{inner})"

    def _compile_function(self, expr: JSON) -> str:
        fn = expr.get("func")
        if not isinstance(fn, str):
            raise DSLValidationError("func must be a string")

        _IdentifierPolicy.validate_identifier(fn, "function name")

        args = expr.get("args", [])
        if not isinstance(args, list):
            raise DSLValidationError("func.args must be a list")

        args_sql = ", ".join(self._compile_expr(a) for a in args)
        return f"{fn.upper()}({args_sql})"

    def _compile_window(self, expr: JSON) -> str:
        fn = str(expr.get("window_fn", "")).lower()
        if fn not in self._WINDOW_FNS:
            raise DSLValidationError(f"Unsupported window function: {fn!r}")

        args = expr.get("args", [])
        if not isinstance(args, list):
            raise DSLValidationError("window args must be a list")

        args_sql = ", ".join(self._compile_expr(a) for a in args)
        base = f"{fn.upper()}({args_sql})"

        over_parts: List[str] = []

        partition_by = expr.get("partition_by", [])
        if partition_by:
            if not isinstance(partition_by, list):
                raise DSLValidationError("partition_by must be a list")
            part_sql = ", ".join(
                self._compile_expr({"field": p} if isinstance(p, str) else p)
                for p in partition_by
            )
            over_parts.append(f"PARTITION BY {part_sql}")

        order_by = expr.get("order_by", [])
        if order_by:
            if not isinstance(order_by, list):
                raise DSLValidationError("window order_by must be a list")
            order_sql = ", ".join(self._compile_order_item(o) for o in order_by)
            over_parts.append(f"ORDER BY {order_sql}")

        frame = expr.get("frame")
        if frame:
            if not isinstance(frame, str):
                raise DSLValidationError("window frame must be a string")
            if not re.match(r"^[A-Za-z0-9_ ()'\-]+$", frame):
                raise DSLValidationError("window frame contains unsupported characters")
            over_parts.append(frame.upper())

        return f"{base} OVER ({' '.join(over_parts)})"

    def _compile_case(self, expr: JSON) -> str:
        cases = expr.get("case")
        if not isinstance(cases, list) or not cases:
            raise DSLValidationError("case must be a non-empty list")

        out: List[str] = ["CASE"]

        for c in cases:
            if not isinstance(c, dict) or "when" not in c or "then" not in c:
                raise DSLValidationError("Each case branch requires 'when' and 'then'")
            when_sql = self._compile_condition(c["when"])
            then_sql = self._compile_expr(c["then"])
            out.append(f"WHEN {when_sql} THEN {then_sql}")

        if "else" in expr:
            out.append(f"ELSE {self._compile_expr(expr['else'])}")

        out.append("END")
        return " ".join(out)

    # ---------------------------------------------------------------------
    # Conditions
    # ---------------------------------------------------------------------

    def _compile_where_like(self, expr: Any, clause_name: str) -> str:
        if expr is None:
            return ""
        cond_sql = self._compile_condition(expr)
        return f"{clause_name} {cond_sql}"

    def _compile_condition(self, expr: Any) -> str:
        if not isinstance(expr, dict):
            raise DSLValidationError("Condition must be an object")

        # Boolean wrappers
        if "and" in expr:
            items = expr["and"]
            if not isinstance(items, list) or not items:
                raise DSLValidationError("and must be a non-empty list")
            return "(" + " AND ".join(self._compile_condition(i) for i in items) + ")"

        if "or" in expr:
            items = expr["or"]
            if not isinstance(items, list) or not items:
                raise DSLValidationError("or must be a non-empty list")
            return "(" + " OR ".join(self._compile_condition(i) for i in items) + ")"

        if "not" in expr:
            return f"NOT ({self._compile_condition(expr['not'])})"

        op = str(expr.get("op", "")).lower()
        if op not in self._PREDICATE_OPS:
            raise DSLValidationError(f"Unsupported predicate operator: {op!r}")

        used_shorthand = "field" in expr

        if used_shorthand:
            left_expr: Any = {"field": expr["field"], "kind": expr.get("kind")}
            right_expr = expr.get("value")
        else:
            left_expr = expr.get("left")
            right_expr = expr.get("right")

        if left_expr is None:
            raise DSLValidationError("Predicate requires 'field' or 'left'")

        left_sql = self._compile_expr(
            left_expr if isinstance(left_expr, dict) else {"field": left_expr}
        )

        if op == "is_null":
            return f"{left_sql} IS NULL"

        if op == "is_not_null":
            return f"{left_sql} IS NOT NULL"

        if op == "between":
            if not isinstance(right_expr, (list, tuple)) or len(right_expr) != 2:
                raise DSLValidationError("between requires value/right as a two-element list")
            low_sql = self._compile_expr({"literal": right_expr[0]})
            high_sql = self._compile_expr({"literal": right_expr[1]})
            return f"{left_sql} BETWEEN {low_sql} AND {high_sql}"

        if op in {"in", "not_in"}:
            if not isinstance(right_expr, (list, tuple)) or not right_expr:
                raise DSLValidationError(f"{op} requires a non-empty array value")
            placeholders = ", ".join(self._compile_expr({"literal": v}) for v in right_expr)
            keyword = "IN" if op == "in" else "NOT IN"
            return f"{left_sql} {keyword} ({placeholders})"

        # Decide whether RHS is expression or literal.
        right_is_expression = False

        if isinstance(right_expr, dict) and any(
            k in right_expr for k in ("field", "agg", "func", "window_fn", "case", "raw_alias")
        ):
            right_is_expression = True
        elif not used_shorthand and isinstance(right_expr, str) and _IdentifierPolicy.is_qualified_ref(right_expr):
            # left/right form may mean column-to-column comparison
            right_is_expression = True

        if right_is_expression:
            right_sql = self._compile_expr(
                right_expr if isinstance(right_expr, dict) else {"field": right_expr}
            )
        else:
            transformed = self._transform_value_by_operator(op, right_expr)
            right_sql = self._compile_expr({"literal": transformed})

        if op == "eq":
            return f"{left_sql} = {right_sql}"
        if op == "ne":
            return f"{left_sql} <> {right_sql}"
        if op == "gt":
            return f"{left_sql} > {right_sql}"
        if op == "gte":
            return f"{left_sql} >= {right_sql}"
        if op == "lt":
            return f"{left_sql} < {right_sql}"
        if op == "lte":
            return f"{left_sql} <= {right_sql}"
        if op == "like":
            return f"{left_sql} LIKE {right_sql}"
        if op == "ilike":
            return self.dialect.render_ilike(left_sql, right_sql)
        if op == "starts_with":
            rhs = self._compile_expr({"literal": f"{right_expr}%"})
            return self.dialect.render_ilike(left_sql, rhs)
        if op == "ends_with":
            rhs = self._compile_expr({"literal": f"%{right_expr}"})
            return self.dialect.render_ilike(left_sql, rhs)
        if op == "contains":
            rhs = self._compile_expr({"literal": f"%{right_expr}%"})
            return self.dialect.render_ilike(left_sql, rhs)

        raise DSLValidationError(f"Unsupported predicate operator: {op!r}")

    def _transform_value_by_operator(self, op: str, value: Any) -> Any:
        if op in {"starts_with", "ends_with", "contains"} and not isinstance(value, str):
            raise DSLValidationError(f"{op} requires a string value")
        return value

    # ---------------------------------------------------------------------
    # GROUP BY / HAVING / QUALIFY
    # ---------------------------------------------------------------------

    def _compile_group_by(self, items: Any) -> str:
        if not items:
            return ""

        if not isinstance(items, list):
            raise DSLValidationError("group_by must be a list")

        parts: List[str] = []
        for item in items:
            if isinstance(item, str):
                parts.append(self._compile_column_ref(item))
            elif isinstance(item, dict):
                parts.append(self._compile_expr(item))
            else:
                raise DSLValidationError("group_by items must be strings or expression objects")

        return "GROUP BY " + ", ".join(parts)

    def _compile_qualify(self, expr: Any) -> str:
        if expr is None:
            return ""

        if self.dialect.name != "databricks":
            raise DSLValidationError(
                "QUALIFY is only supported for the databricks dialect in this library"
            )

        cond_sql = self._compile_condition(expr)
        return f"QUALIFY {cond_sql}"

    # ---------------------------------------------------------------------
    # ORDER BY
    # ---------------------------------------------------------------------

    def _compile_order_by(self, items: Any) -> str:
        if not items:
            return ""

        if not isinstance(items, list):
            raise DSLValidationError("order_by must be a list")

        parts = [self._compile_order_item(item) for item in items]
        return "ORDER BY " + ", ".join(parts)

    def _compile_order_item(self, item: Any) -> str:
        if isinstance(item, str):
            return f"{self._compile_column_ref(item)} ASC"

        if not isinstance(item, dict):
            raise DSLValidationError("order_by items must be strings or objects")

        direction = str(item.get("dir", "asc")).lower()
        if direction not in self._ORDER_DIRS:
            raise DSLValidationError(f"Unsupported order direction: {direction!r}")

        nulls = item.get("nulls")
        nulls_sql = ""
        if nulls is not None:
            nulls_l = str(nulls).lower()
            if nulls_l not in self._NULLS_POS:
                raise DSLValidationError("nulls must be 'first' or 'last'")
            nulls_sql = f" NULLS {nulls_l.upper()}"

        if "field" in item:
            expr_sql = self._compile_field_or_alias(item["field"], item.get("kind"))
        elif "expr" in item:
            expr_sql = self._compile_expr(item["expr"])
        else:
            raise DSLValidationError("order_by item requires 'field' or 'expr'")

        return f"{expr_sql} {direction.upper()}{nulls_sql}"

    # ---------------------------------------------------------------------
    # LIMIT / OFFSET
    # ---------------------------------------------------------------------

    def _compile_limit_offset(self, limit: Any, offset: Any) -> str:
        if limit is not None:
            if not isinstance(limit, int) or limit < 0:
                raise DSLValidationError("limit must be a non-negative integer")

        if offset is not None:
            if not isinstance(offset, int) or offset < 0:
                raise DSLValidationError("offset must be a non-negative integer")

        return self.dialect.render_limit_offset(limit, offset)


def compile_json_dsl(
    dsl: Union[str, JSON],
    dialect: str = "postgres",
    metadata: Optional[JSON] = None,
    strict_alias_resolution: bool = True,
    quote_aliases: bool = False,
) -> CompiledQuery:
    """
    Convenience wrapper.

    Parameters
    ----------
    dsl:
        Python dict or JSON string

    dialect:
        'postgres' or 'databricks'

    metadata:
        Optional allowlist metadata

    strict_alias_resolution:
        Validate alias references against FROM/JOIN aliases

    quote_aliases:
        Quote aliases in the SQL output
    """
    if isinstance(dsl, str):
        dsl = json.loads(dsl)

    compiler = SqlCompiler(
        dialect=dialect,
        metadata=metadata,
        strict_alias_resolution=strict_alias_resolution,
        quote_aliases=quote_aliases,
    )
    return compiler.compile(dsl)


# =========================================================================
# DEMO / SELF-TEST
# =========================================================================

if __name__ == "__main__":
    metadata = {
        "tables": {
            "claims": {
                "columns": [
                    "claim_id",
                    "member_id",
                    "claim_status",
                    "service_date",
                    "paid_amount",
                    "provider_id",
                ]
            },
            "members": {
                "columns": [
                    "member_id",
                    "member_name",
                    "region",
                ]
            },
            "providers": {
                "columns": [
                    "provider_id",
                    "provider_name",
                ]
            },
        }
    }

    dsl = {
        "from": {"table": "claims", "alias": "c"},
        "joins": [
            {
                "type": "left",
                "table": "members",
                "alias": "m",
                "on": {"left": "c.member_id", "op": "eq", "right": "m.member_id"},
            },
            {
                "type": "left",
                "table": "providers",
                "alias": "p",
                "on": {"left": "c.provider_id", "op": "eq", "right": "p.provider_id"},
            },
        ],
        "select": [
            {"field": "m.region", "as": "region"},
            {"field": "c.claim_status", "as": "claim_status"},
            {"agg": "count", "field": "c.claim_id", "as": "claim_count"},
            {"agg": "sum", "field": "c.paid_amount", "as": "total_paid"},
            {
                "window_fn": "dense_rank",
                "partition_by": ["m.region"],
                "order_by": [{"field": "c.paid_amount", "dir": "desc"}],
                "as": "region_paid_rank",
            },
            {
                "case": [
                    {
                        "when": {"field": "c.paid_amount", "op": "gte", "value": 1000},
                        "then": {"literal": "HIGH"},
                    },
                    {
                        "when": {"field": "c.paid_amount", "op": "gte", "value": 500},
                        "then": {"literal": "MEDIUM"},
                    },
                ],
                "else": {"literal": "LOW"},
                "as": "paid_band",
            },
        ],
        "where": {
            "and": [
                {"field": "c.claim_status", "op": "in", "value": ["PAID", "DENIED"]},
                {
                    "field": "c.service_date",
                    "op": "between",
                    "value": ["2026-01-01", "2026-03-31"],
                },
                {"field": "p.provider_name", "op": "contains", "value": "care"},
            ]
        },
        "group_by": ["m.region", "c.claim_status"],
        "having": {
            "and": [
                {
                    "left": {"agg": "sum", "field": "c.paid_amount"},
                    "op": "gte",
                    "right": 10000,
                }
            ]
        },
        "order_by": [
            {"field": "region", "kind": "alias", "dir": "asc"},
            {"field": "total_paid", "kind": "alias", "dir": "desc"},
        ],
        "limit": 100,
        "offset": 0,
    }

    for target in ("postgres", "databricks"):
        compiled = compile_json_dsl(dsl, dialect=target, metadata=metadata)
        print("=" * 80)
        print(target.upper())
        print(compiled.sql)
        print("PARAMS:", compiled.params)