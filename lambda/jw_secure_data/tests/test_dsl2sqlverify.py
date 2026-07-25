from query.datamap import load_datamap
from query.dsl2sqlverify import DSLVerificationError, assert_valid_dsl, verify_dsl


def _valid_dsl():
    return {
        "from": {"table": "claims", "alias": "c"},
        "select": [{"field": "c.claim_id", "as": "claim_id"}],
        "limit": 10,
    }


def test_verify_dsl_accepts_valid_query():
    result = verify_dsl(_valid_dsl(), load_datamap())
    assert result.valid is True
    assert not result.errors
    assert result.compiled_sql
    assert "FROM" in result.compiled_sql


def test_verify_dsl_rejects_unknown_table():
    dsl = _valid_dsl()
    dsl["from"]["table"] = "unknown_table"
    result = verify_dsl(dsl, load_datamap())
    assert result.valid is False
    assert any("unknown_table" in error for error in result.errors)


def test_verify_dsl_requires_limit_for_chat_queries():
    dsl = _valid_dsl()
    del dsl["limit"]
    result = verify_dsl(dsl, load_datamap())
    assert result.valid is False
    assert any("limit is required" in error for error in result.errors)


def test_assert_valid_dsl_raises_for_invalid_query():
    try:
        assert_valid_dsl({"select": []}, load_datamap())
    except DSLVerificationError as exc:
        assert exc.errors
    else:
        raise AssertionError("expected DSLVerificationError")
