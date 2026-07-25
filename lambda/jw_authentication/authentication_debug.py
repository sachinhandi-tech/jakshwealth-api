"""Compact authentication logging: configured groups vs session membership."""

from __future__ import annotations

import os


def configured_groups() -> dict[str, str]:
    return {
        "USER_GG": os.environ.get("USER_GG", "").strip(),
        "ADMIN_GG": os.environ.get("ADMIN_GG", "").strip(),
    }


def membership_summary(caller_groups: list[str]) -> dict:
    cfg = configured_groups()
    caller = list(caller_groups or [])
    return {
        "USER_GG": cfg["USER_GG"],
        "ADMIN_GG": cfg["ADMIN_GG"],
        "inUserGg": bool(cfg["USER_GG"] and cfg["USER_GG"] in caller),
        "inAdminGg": bool(cfg["ADMIN_GG"] and cfg["ADMIN_GG"] in caller),
    }
