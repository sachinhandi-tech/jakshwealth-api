"""Map Okta global groups to application roles (matches jw_authorization)."""

from __future__ import annotations

import os

USER_ROLE = "user"
ADMIN_ROLE = "admin"


def resolve_roles(caller_groups: list[str]) -> list[str]:
    roles = []
    user_group = os.environ.get("USER_GG", "").strip()
    admin_group = os.environ.get("ADMIN_GG", "").strip()
    if user_group and user_group in caller_groups:
        roles.append(USER_ROLE)
    if admin_group and admin_group in caller_groups:
        roles.append(ADMIN_ROLE)
    return roles
