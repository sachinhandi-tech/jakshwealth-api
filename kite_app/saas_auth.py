"""Multi-tenant authentication and authorization."""

from __future__ import annotations

import hashlib
import uuid
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from kite_app.saas_models import ApiKey, OrganizationUser, Organization
from kite_app.saas_config import get_tier_config


class TenantContext:
    """Request context with tenant (organization) information."""

    def __init__(self, org_id: uuid.UUID, user_id: Optional[uuid.UUID], role: str):
        self.org_id = org_id
        self.user_id = user_id
        self.role = role


async def extract_tenant_context(request: Request, db: Session) -> TenantContext:
    """Extract organization context from request."""
    # Try API key first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]
        return await authenticate_api_key(api_key, db)

    # Fall back to session/JWT (implemented later)
    raise HTTPException(status_code=401, detail="Missing or invalid authentication")


async def authenticate_api_key(api_key_str: str, db: Session) -> TenantContext:
    """Authenticate with API key and return tenant context."""
    # Hash the provided key
    key_hash = hashlib.sha256(api_key_str.encode()).hexdigest()

    # Look up the key
    api_key = db.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active == True,
    ).first()

    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check if expired
    if api_key.expires_at and api_key.expires_at < __import__("datetime").datetime.now():
        raise HTTPException(status_code=401, detail="API key expired")

    # Get user for role
    user = db.query(OrganizationUser).filter(
        OrganizationUser.user_id == api_key.user_id
    ).first()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not active")

    # Update last used timestamp
    api_key.last_used_at = __import__("datetime").datetime.now()
    db.commit()

    return TenantContext(
        org_id=api_key.org_id,
        user_id=api_key.user_id,
        role=user.role,
    )


def check_permission(context: TenantContext, required_role: str) -> bool:
    """Check if user has required role."""
    role_hierarchy = {"admin": 3, "member": 2, "viewer": 1}
    return role_hierarchy.get(context.role, 0) >= role_hierarchy.get(required_role, 0)


def enforce_organization(context: TenantContext, org_id: str) -> None:
    """Enforce that context organization matches requested organization."""
    if str(context.org_id) != org_id:
        raise HTTPException(status_code=403, detail="Access denied: organization mismatch")


def check_tier_feature(context: TenantContext, db: Session, feature: str) -> bool:
    """Check if organization's tier has access to a feature."""
    org = db.query(Organization).filter(
        Organization.org_id == context.org_id
    ).first()

    if not org:
        return False

    config = get_tier_config(org.subscription_tier)
    return feature in config.get("features", [])


def can_scan_all_nse(context: TenantContext, db: Session) -> bool:
    """Check if organization's tier allows all NSE scanning."""
    org = db.query(Organization).filter(
        Organization.org_id == context.org_id
    ).first()

    if not org:
        return False

    from kite_app.saas_config import can_scan_all_nse as tier_can_scan
    return tier_can_scan(org.subscription_tier)


def generate_api_key(org_id: uuid.UUID, user_id: uuid.UUID, db: Session, name: str = "API Key") -> str:
    """Generate a new API key for a user."""
    # Generate random key
    key_str = str(uuid.uuid4()) + str(uuid.uuid4())
    key_hash = hashlib.sha256(key_str.encode()).hexdigest()

    # Store hashed key
    api_key = ApiKey(
        key_id=uuid.uuid4(),
        org_id=org_id,
        user_id=user_id,
        key_hash=key_hash,
        name=name,
        is_active=True,
        created_at=__import__("datetime").datetime.now(),
    )
    db.add(api_key)
    db.commit()

    # Return unhashed key (only shown once)
    return key_str
