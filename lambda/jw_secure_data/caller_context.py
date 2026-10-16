"""Read caller identity passed from ``jw_authorization`` authorizer context."""


def roles_from_authorizer(authorizer: dict) -> list[str]:
    raw = (authorizer or {}).get("roles", "")
    if not raw:
        return []
    return [role.strip() for role in str(raw).split(",") if role.strip()]


def lan_id_from_authorizer(authorizer: dict) -> str:
    authorizer = authorizer or {}
    return authorizer.get("lanId") or authorizer.get("principalId") or "unknown"
