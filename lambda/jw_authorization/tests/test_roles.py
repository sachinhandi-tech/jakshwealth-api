import os

from roles import resolve_roles


def test_user_role_only(monkeypatch):
    monkeypatch.setenv("USER_GG", "TEST_USER_GROUP")
    monkeypatch.setenv("ADMIN_GG", "TEST_ADMIN_GROUP")
    assert resolve_roles(["TEST_USER_GROUP"]) == ["user"]


def test_admin_role_only(monkeypatch):
    monkeypatch.setenv("USER_GG", "TEST_USER_GROUP")
    monkeypatch.setenv("ADMIN_GG", "TEST_ADMIN_GROUP")
    assert resolve_roles(["TEST_ADMIN_GROUP"]) == ["admin"]


def test_user_and_admin_roles(monkeypatch):
    monkeypatch.setenv("USER_GG", "TEST_USER_GROUP")
    monkeypatch.setenv("ADMIN_GG", "TEST_ADMIN_GROUP")
    groups = ["TEST_USER_GROUP", "TEST_ADMIN_GROUP"]
    assert resolve_roles(groups) == ["user", "admin"]
