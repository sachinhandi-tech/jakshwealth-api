"""Map Okta global groups to application roles for downstream Lambdas."""

from __future__ import annotations

import os

USER_ROLE = "user"
ADMIN_ROLE = "admin"


def resolve_roles(caller_groups: list[str]) -> list[str]:
    """Return role labels for group membership (e.g. ``['user']`` or ``['user', 'admin']``)."""
    roles = []
    user_group = os.environ.get("USER_GG", "").strip()
    admin_group = os.environ.get("ADMIN_GG", "").strip()
    if user_group and user_group in caller_groups:
        roles.append(USER_ROLE)
    if admin_group and admin_group in caller_groups:
        roles.append(ADMIN_ROLE)
    return roles
