from query.datamap import (
    compiler_metadata,
    load_datamap,
    physical_table_name,
    query_dialect,
    resolve_physical_dsl,
    table_names,
)


def test_load_datamap_contains_expected_tables():
    datamap = load_datamap()
    assert table_names(datamap) == {
        "claims",
        "claim_lines",
        "members",
        "providers",
        "provider_groups",
    }
    assert query_dialect(datamap) == "databricks"


def test_compiler_metadata_flattens_column_descriptions():
    datamap = load_datamap()
    metadata = compiler_metadata(datamap)
    assert "claims" in metadata["tables"]
    assert "claim_id" in metadata["tables"]["claims"]["columns"]


def test_physical_table_name_resolves_logical_tables():
    datamap = load_datamap()
    assert physical_table_name(datamap, "claims") == "claim_fact"
    assert physical_table_name(datamap, "members") == "member_dim"


def test_resolve_physical_dsl_rewrites_from_and_join_tables():
    datamap = load_datamap()
    dsl = {
        "from": {"table": "claims", "alias": "c"},
        "joins": [
            {
                "type": "left",
                "table": "members",
                "alias": "m",
                "on": {"left": "c.member_id", "op": "eq", "right": "m.member_id"},
            }
        ],
        "select": [{"field": "c.claim_id", "as": "claim_id"}],
        "limit": 10,
    }
    resolved = resolve_physical_dsl(dsl, datamap)
    assert resolved["from"]["table"] == "claim_fact"
    assert resolved["joins"][0]["table"] == "member_dim"
