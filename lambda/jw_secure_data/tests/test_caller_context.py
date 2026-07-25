from caller_context import lan_id_from_authorizer, roles_from_authorizer


def test_roles_parsed_from_comma_separated_context():
    assert roles_from_authorizer({"roles": "user,admin"}) == ["user", "admin"]


def test_lan_id_prefers_authorizer_lan_id():
    assert lan_id_from_authorizer({"lanId": "TESTUSER01", "principalId": "other"}) == "TESTUSER01"
