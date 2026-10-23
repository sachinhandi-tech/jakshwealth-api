"""SaaS admin APIs for organization and user management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr

from kite_app.saas_models import (
    Organization, OrganizationUser, Subscription, SubscriptionTier,
    SaasBase
)
from kite_app.saas_config import get_tier_config
from kite_app.models import get_sessionmaker

router = APIRouter(tags=["saas-admin"], prefix="/api/admin")

@router.get("/me")
def get_current_user_org(platform_user_id: str = Header(None, alias="X-Platform-User-Id")) -> dict:
    """Get current user's organization ID and details."""
    if not platform_user_id:
        raise HTTPException(status_code=401, detail="Platform user ID required")
    
    db = get_sessionmaker()()
    try:
        # Find organization by platform user ID (stored in user's session)
        # For now, return a default org_id - in production this would query from sessions table
        user = db.query(OrganizationUser).filter(
            OrganizationUser.email.like(platform_user_id)  # Simplified lookup
        ).first()
        
        if not user:
            raise HTTPException(status_code=404, detail="User organization not found")
        
        org = db.query(Organization).filter(
            Organization.org_id == user.org_id
        ).first()
        
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        
        return {
            "org_id": str(org.org_id),
            "user_id": str(user.user_id),
            "name": org.name,
            "email": org.email,
            "subscription_tier": org.subscription_tier,
            "user_role": user.role,
        }
    finally:
        db.close()



class OrgCreate(BaseModel):
    """Create organization request."""
    name: str
    email: EmailStr
    admin_name: str


class OrgResponse(BaseModel):
    """Organization response."""
    org_id: str
    name: str
    email: str
    slug: str
    subscription_tier: str
    is_active: bool
    created_at: str


class UserCreate(BaseModel):
    """Create organization user request."""
    email: EmailStr
    name: str
    role: str = "member"  # admin, member, viewer


class UserResponse(BaseModel):
    """Organization user response."""
    user_id: str
    email: str
    name: str
    role: str
    is_active: bool
    created_at: str


@router.post("/organizations", response_model=OrgResponse)
def create_organization(req: OrgCreate) -> dict:
    """Create new organization (used during signup)."""
    db = get_sessionmaker()()
    try:
        # Check if organization exists
        existing = db.query(Organization).filter(
            Organization.email == req.email
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Organization already exists")

        # Create slug from name
        slug = req.name.lower().replace(" ", "-")[:128]

        # Create organization
        org = Organization(
            org_id=uuid.uuid4(),
            name=req.name,
            email=req.email,
            slug=slug,
            subscription_tier=SubscriptionTier.FREE,
            is_active=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(org)

        # Create default subscription
        subscription = Subscription(
            subscription_id=uuid.uuid4(),
            org_id=org.org_id,
            tier=SubscriptionTier.FREE,
            status="active",
            start_date=datetime.now().date(),
            auto_renew=True,
            billing_cycle="monthly",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(subscription)

        # Create admin user
        admin_user = OrganizationUser(
            user_id=uuid.uuid4(),
            org_id=org.org_id,
            email=req.email,
            name=req.admin_name,
            role="admin",
            is_active=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(admin_user)

        db.commit()

        return {
            "org_id": str(org.org_id),
            "name": org.name,
            "email": org.email,
            "slug": org.slug,
            "subscription_tier": org.subscription_tier,
            "is_active": org.is_active,
            "created_at": org.created_at.isoformat(),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.get("/organizations/{org_id}", response_model=OrgResponse)
def get_organization(org_id: str) -> dict:
    """Get organization details."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(org_id)
        ).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        return {
            "org_id": str(org.org_id),
            "name": org.name,
            "email": org.email,
            "slug": org.slug,
            "subscription_tier": org.subscription_tier,
            "is_active": org.is_active,
            "created_at": org.created_at.isoformat(),
        }
    finally:
        db.close()


@router.post("/organizations/{org_id}/users", response_model=UserResponse)
def create_user(org_id: str, req: UserCreate) -> dict:
    """Create user in organization."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(org_id)
        ).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Check if user already exists
        existing = db.query(OrganizationUser).filter(
            OrganizationUser.org_id == org.org_id,
            OrganizationUser.email == req.email
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="User already exists")

        # Create user
        user = OrganizationUser(
            user_id=uuid.uuid4(),
            org_id=org.org_id,
            email=req.email,
            name=req.name,
            role=req.role,
            is_active=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(user)
        db.commit()

        return {
            "user_id": str(user.user_id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.get("/organizations/{org_id}/users")
def list_users(org_id: str) -> dict:
    """List all users in organization."""
    db = get_sessionmaker()()
    try:
        users = db.query(OrganizationUser).filter(
            OrganizationUser.org_id == uuid.UUID(org_id)
        ).all()

        return {
            "users": [
                {
                    "user_id": str(u.user_id),
                    "email": u.email,
                    "name": u.name,
                    "role": u.role,
                    "is_active": u.is_active,
                    "created_at": u.created_at.isoformat(),
                }
                for u in users
            ]
        }
    finally:
        db.close()


@router.patch("/organizations/{org_id}/users/{user_id}")
def update_user(org_id: str, user_id: str, is_active: Optional[bool] = None, role: Optional[str] = None) -> dict:
    """Update user (suspend/revoke or change role)."""
    db = get_sessionmaker()()
    try:
        user = db.query(OrganizationUser).filter(
            OrganizationUser.user_id == uuid.UUID(user_id),
            OrganizationUser.org_id == uuid.UUID(org_id)
        ).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if is_active is not None:
            user.is_active = is_active
        if role is not None and role in ["admin", "member", "viewer"]:
            user.role = role

        user.updated_at = datetime.now()
        db.commit()

        return {
            "user_id": str(user.user_id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.get("/organizations/{org_id}/limits")
def get_org_limits(org_id: str) -> dict:
    """Get tier limits for organization."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(org_id)
        ).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        config = get_tier_config(org.subscription_tier)
        return {
            "tier": org.subscription_tier,
            **config,
        }
    finally:
        db.close()
