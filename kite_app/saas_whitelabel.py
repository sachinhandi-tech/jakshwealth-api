"""White-label support for custom domains and branding."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kite_app.saas_models import Organization, WhiteLabel
from kite_app.saas_auth import TenantContext
from kite_app.models import get_sessionmaker

router = APIRouter(tags=["whitelabel"], prefix="/api/whitelabel")


class WhiteLabelConfig(BaseModel):
    """White-label configuration."""
    org_id: str
    company_name: str
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    custom_domain: Optional[str] = None
    support_email: Optional[str] = None
    privacy_policy_url: Optional[str] = None
    terms_of_service_url: Optional[str] = None


class WhiteLabelResponse(BaseModel):
    """White-label response."""
    org_id: str
    company_name: str
    logo_url: Optional[str]
    primary_color: Optional[str]
    secondary_color: Optional[str]
    custom_domain: Optional[str]
    support_email: Optional[str]


@router.get("/config/{org_id}", response_model=WhiteLabelResponse)
def get_whitelabel_config(org_id: str) -> dict:
    """Get white-label configuration for organization."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(org_id)
        ).first()

        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        config = db.query(WhiteLabel).filter(
            WhiteLabel.org_id == org.org_id
        ).first()

        if not config:
            # Return default branding
            return {
                "org_id": org_id,
                "company_name": org.name,
                "logo_url": None,
                "primary_color": None,
                "secondary_color": None,
                "custom_domain": None,
                "support_email": None,
            }

        return {
            "org_id": org_id,
            "company_name": config.company_name,
            "logo_url": config.logo_url,
            "primary_color": config.primary_color,
            "secondary_color": config.secondary_color,
            "custom_domain": config.custom_domain,
            "support_email": config.support_email,
        }
    finally:
        db.close()


@router.post("/config", response_model=WhiteLabelResponse)
def update_whitelabel_config(req: WhiteLabelConfig, context: Optional[TenantContext] = None) -> dict:
    """Update white-label configuration."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(req.org_id)
        ).first()

        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Check if org has white-label tier
        if org.subscription_tier != "enterprise":
            raise HTTPException(
                status_code=403,
                detail="White-label is only available for Enterprise tier"
            )

        config = db.query(WhiteLabel).filter(
            WhiteLabel.org_id == org.org_id
        ).first()

        if not config:
            config = WhiteLabel(
                whitelabel_id=uuid.uuid4(),
                org_id=org.org_id,
                company_name=req.company_name,
                logo_url=req.logo_url,
                primary_color=req.primary_color,
                secondary_color=req.secondary_color,
                custom_domain=req.custom_domain,
                support_email=req.support_email,
                privacy_policy_url=req.privacy_policy_url,
                terms_of_service_url=req.terms_of_service_url,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(config)
        else:
            config.company_name = req.company_name
            if req.logo_url:
                config.logo_url = req.logo_url
            if req.primary_color:
                config.primary_color = req.primary_color
            if req.secondary_color:
                config.secondary_color = req.secondary_color
            if req.custom_domain:
                config.custom_domain = req.custom_domain
            if req.support_email:
                config.support_email = req.support_email
            if req.privacy_policy_url:
                config.privacy_policy_url = req.privacy_policy_url
            if req.terms_of_service_url:
                config.terms_of_service_url = req.terms_of_service_url
            config.updated_at = datetime.now()

        db.commit()

        return {
            "org_id": req.org_id,
            "company_name": config.company_name,
            "logo_url": config.logo_url,
            "primary_color": config.primary_color,
            "secondary_color": config.secondary_color,
            "custom_domain": config.custom_domain,
            "support_email": config.support_email,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.get("/domain/{domain}")
def get_org_by_domain(domain: str) -> dict:
    """Get organization by custom domain."""
    db = get_sessionmaker()()
    try:
        config = db.query(WhiteLabel).filter(
            WhiteLabel.custom_domain == domain
        ).first()

        if not config:
            raise HTTPException(status_code=404, detail="Domain not found")

        org = db.query(Organization).filter(
            Organization.org_id == config.org_id
        ).first()

        return {
            "org_id": str(org.org_id),
            "name": org.name,
            "company_name": config.company_name,
            "logo_url": config.logo_url,
            "primary_color": config.primary_color,
            "secondary_color": config.secondary_color,
            "support_email": config.support_email,
        }
    finally:
        db.close()


def get_whitelabel_branding(org_id: uuid.UUID, db: Session) -> dict:
    """Get branding for rendering white-label UI."""
    config = db.query(WhiteLabel).filter(
        WhiteLabel.org_id == org_id
    ).first()

    if not config:
        org = db.query(Organization).filter(
            Organization.org_id == org_id
        ).first()
        return {
            "company_name": org.name if org else "jakshwealth",
            "logo_url": None,
            "primary_color": "#1f2937",
            "secondary_color": "#3b82f6",
        }

    return {
        "company_name": config.company_name,
        "logo_url": config.logo_url,
        "primary_color": config.primary_color or "#1f2937",
        "secondary_color": config.secondary_color or "#3b82f6",
    }
