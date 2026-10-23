"""Subscription management and tier handling."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kite_app.saas_models import Organization, Subscription, SubscriptionTier, AuditLog
from kite_app.saas_config import get_monthly_price, get_tier_config
from kite_app.models import get_sessionmaker

router = APIRouter(tags=["subscriptions"], prefix="/api/subscriptions")


class SubscriptionResponse(BaseModel):
    """Subscription response."""
    subscription_id: str
    tier: str
    status: str
    start_date: str
    end_date: Optional[str]
    next_billing_date: Optional[str]
    auto_renew: bool
    billing_cycle: str


class UpgradeRequest(BaseModel):
    """Subscription upgrade/downgrade request."""
    org_id: str
    new_tier: str
    billing_cycle: str = "monthly"  # monthly or yearly


@router.get("/organizations/{org_id}/subscription", response_model=SubscriptionResponse)
def get_subscription(org_id: str) -> dict:
    """Get current subscription for organization."""
    db = get_sessionmaker()()
    try:
        sub = db.query(Subscription).filter(
            Subscription.org_id == uuid.UUID(org_id),
            Subscription.status == "active"
        ).first()

        if not sub:
            raise HTTPException(status_code=404, detail="No active subscription found")

        return {
            "subscription_id": str(sub.subscription_id),
            "tier": sub.tier,
            "status": sub.status,
            "start_date": sub.start_date.isoformat(),
            "end_date": sub.end_date.isoformat() if sub.end_date else None,
            "next_billing_date": sub.next_billing_date.isoformat() if sub.next_billing_date else None,
            "auto_renew": sub.auto_renew,
            "billing_cycle": sub.billing_cycle,
        }
    finally:
        db.close()


@router.post("/organizations/{org_id}/upgrade", response_model=SubscriptionResponse)
def upgrade_subscription(org_id: str, req: UpgradeRequest) -> dict:
    """Upgrade or downgrade subscription tier."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(org_id)
        ).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Validate tier
        if req.new_tier not in [t.value for t in SubscriptionTier]:
            raise HTTPException(status_code=400, detail="Invalid subscription tier")

        # Get current subscription
        current_sub = db.query(Subscription).filter(
            Subscription.org_id == org.org_id,
            Subscription.status == "active"
        ).first()

        if not current_sub:
            raise HTTPException(status_code=404, detail="No active subscription found")

        # Same tier, no change needed
        if current_sub.tier == req.new_tier and current_sub.billing_cycle == req.billing_cycle:
            raise HTTPException(status_code=400, detail="Already on this tier and billing cycle")

        # Cancel old subscription
        current_sub.status = "cancelled"
        current_sub.end_date = datetime.now().date()

        # Create new subscription
        today = datetime.now().date()
        if req.billing_cycle == "yearly":
            end_date = today + timedelta(days=365)
        else:
            end_date = today + timedelta(days=30)

        new_sub = Subscription(
            subscription_id=uuid.uuid4(),
            org_id=org.org_id,
            tier=req.new_tier,
            status="active",
            start_date=today,
            end_date=end_date,
            auto_renew=True,
            billing_cycle=req.billing_cycle,
            next_billing_date=end_date,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(new_sub)

        # Update organization tier
        org.subscription_tier = req.new_tier
        org.updated_at = datetime.now()

        # Log audit
        audit = AuditLog(
            log_id=uuid.uuid4(),
            org_id=org.org_id,
            action="subscription_upgraded",
            resource_type="subscription",
            resource_id=str(new_sub.subscription_id),
            details={
                "from_tier": current_sub.tier,
                "to_tier": req.new_tier,
                "billing_cycle": req.billing_cycle,
            },
            created_at=datetime.now(),
        )
        db.add(audit)

        db.commit()

        return {
            "subscription_id": str(new_sub.subscription_id),
            "tier": new_sub.tier,
            "status": new_sub.status,
            "start_date": new_sub.start_date.isoformat(),
            "end_date": new_sub.end_date.isoformat() if new_sub.end_date else None,
            "next_billing_date": new_sub.next_billing_date.isoformat() if new_sub.next_billing_date else None,
            "auto_renew": new_sub.auto_renew,
            "billing_cycle": new_sub.billing_cycle,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.post("/organizations/{org_id}/cancel")
def cancel_subscription(org_id: str) -> dict:
    """Cancel subscription (downgrade to free)."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(org_id)
        ).first()
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        current_sub = db.query(Subscription).filter(
            Subscription.org_id == org.org_id,
            Subscription.status == "active"
        ).first()

        if not current_sub:
            raise HTTPException(status_code=404, detail="No active subscription found")

        # Cancel current
        current_sub.status = "cancelled"
        current_sub.end_date = datetime.now().date()

        # Create free subscription
        today = datetime.now().date()
        free_sub = Subscription(
            subscription_id=uuid.uuid4(),
            org_id=org.org_id,
            tier=SubscriptionTier.FREE,
            status="active",
            start_date=today,
            auto_renew=True,
            billing_cycle="monthly",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(free_sub)

        # Update organization
        org.subscription_tier = SubscriptionTier.FREE
        org.updated_at = datetime.now()

        # Log audit
        audit = AuditLog(
            log_id=uuid.uuid4(),
            org_id=org.org_id,
            action="subscription_cancelled",
            resource_type="subscription",
            resource_id=str(current_sub.subscription_id),
            details={"cancelled_tier": current_sub.tier},
            created_at=datetime.now(),
        )
        db.add(audit)

        db.commit()

        return {
            "message": "Subscription cancelled and downgraded to FREE tier",
            "new_tier": SubscriptionTier.FREE,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


def renew_subscription(subscription_id: uuid.UUID, db: Session) -> None:
    """Renew subscription on expiry (called by scheduled job)."""
    sub = db.query(Subscription).filter(
        Subscription.subscription_id == subscription_id
    ).first()

    if not sub or not sub.auto_renew:
        return

    # Create new subscription period
    today = datetime.now().date()
    if sub.billing_cycle == "yearly":
        end_date = today + timedelta(days=365)
    else:
        end_date = today + timedelta(days=30)

    sub.start_date = today
    sub.end_date = end_date
    sub.next_billing_date = end_date
    sub.updated_at = datetime.now()
    db.commit()


def get_expiring_subscriptions(days_until: int, db: Session) -> list:
    """Get subscriptions expiring in N days."""
    expiry_date = datetime.now().date() + timedelta(days=days_until)
    return db.query(Subscription).filter(
        Subscription.status == "active",
        Subscription.auto_renew == True,
        Subscription.end_date == expiry_date,
    ).all()
