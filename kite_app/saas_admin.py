"""Admin dashboard endpoints for SaaS analytics and reporting."""

from __future__ import annotations

import uuid
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from kite_app.saas_models import Organization, OrganizationUser, Subscription, UsageMetrics, AuditLog, BillingRecord
from kite_app.models import get_sessionmaker

router = APIRouter(tags=["admin-analytics"], prefix="/api/analytics")


class OrgMetrics(BaseModel):
    """Organization metrics."""
    org_id: str
    name: str
    tier: str
    users: int
    active_users: int
    subscriptions: int


class DashboardStats(BaseModel):
    """Dashboard statistics."""
    total_organizations: int
    total_users: int
    total_active_subscriptions: int
    total_monthly_revenue: float
    organizations: list[OrgMetrics]


class UsageReport(BaseModel):
    """Usage report for organization."""
    org_id: str
    period: str
    api_calls: int
    signal_scans: int
    nifty100_scans: int
    all_nse_scans: int
    trades_created: int


class BillingReport(BaseModel):
    """Billing report."""
    org_id: str
    tier: str
    monthly_price: float
    billing_cycle: str
    total_revenue: float
    total_invoices: int


@router.get("/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats() -> dict:
    """Get overall platform dashboard statistics."""
    db = get_sessionmaker()()
    try:
        total_orgs = db.query(func.count(Organization.org_id)).scalar() or 0
        total_users = db.query(func.count(OrganizationUser.user_id)).scalar() or 0
        
        active_subs = db.query(func.count(Subscription.subscription_id)).filter(
            Subscription.status == "active"
        ).scalar() or 0
        
        # Calculate monthly revenue
        today = date.today()
        month_start = date(today.year, today.month, 1)
        
        total_revenue = db.query(func.sum(BillingRecord.amount)).filter(
            BillingRecord.created_at >= month_start,
            BillingRecord.status == "paid",
        ).scalar() or 0

        # Get org metrics
        orgs = db.query(Organization).all()
        org_metrics = []
        for org in orgs:
            user_count = db.query(func.count(OrganizationUser.user_id)).filter(
                OrganizationUser.org_id == org.org_id
            ).scalar() or 0
            
            active_user_count = db.query(func.count(OrganizationUser.user_id)).filter(
                OrganizationUser.org_id == org.org_id,
                OrganizationUser.is_active == True,
            ).scalar() or 0
            
            sub_count = db.query(func.count(Subscription.subscription_id)).filter(
                Subscription.org_id == org.org_id
            ).scalar() or 0

            org_metrics.append(OrgMetrics(
                org_id=str(org.org_id),
                name=org.name,
                tier=org.subscription_tier,
                users=user_count,
                active_users=active_user_count,
                subscriptions=sub_count,
            ))

        return {
            "total_organizations": total_orgs,
            "total_users": total_users,
            "total_active_subscriptions": active_subs,
            "total_monthly_revenue": float(total_revenue),
            "organizations": org_metrics,
        }
    finally:
        db.close()


@router.get("/organizations/{org_id}/usage", response_model=UsageReport)
def get_org_usage(org_id: str, period: str = "current_month") -> dict:
    """Get usage report for organization."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(org_id)
        ).first()
        
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        today = date.today()
        if period == "current_month":
            month_start = date(today.year, today.month, 1)
            metrics = db.query(UsageMetrics).filter(
                UsageMetrics.org_id == org.org_id,
                UsageMetrics.period_date >= month_start,
            ).all()
        elif period == "last_month":
            first_today = date(today.year, today.month, 1)
            month_start = first_today - timedelta(days=first_today.day)
            month_end = first_today - timedelta(days=1)
            metrics = db.query(UsageMetrics).filter(
                UsageMetrics.org_id == org.org_id,
                UsageMetrics.period_date >= month_start,
                UsageMetrics.period_date <= month_end,
            ).all()
        else:
            raise HTTPException(status_code=400, detail="Invalid period")

        total_api = sum(m.api_calls for m in metrics)
        total_scans = sum(m.signal_scans for m in metrics)
        total_nifty100 = sum(m.nifty100_scans for m in metrics)
        total_nse = sum(m.all_nse_scans for m in metrics)
        total_trades = sum(m.trades_created for m in metrics)

        return {
            "org_id": org_id,
            "period": period,
            "api_calls": total_api,
            "signal_scans": total_scans,
            "nifty100_scans": total_nifty100,
            "all_nse_scans": total_nse,
            "trades_created": total_trades,
        }
    finally:
        db.close()


@router.get("/organizations/{org_id}/billing", response_model=BillingReport)
def get_org_billing(org_id: str) -> dict:
    """Get billing report for organization."""
    db = get_sessionmaker()()
    try:
        org = db.query(Organization).filter(
            Organization.org_id == uuid.UUID(org_id)
        ).first()
        
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        sub = db.query(Subscription).filter(
            Subscription.org_id == org.org_id,
            Subscription.status == "active",
        ).first()

        if not sub:
            raise HTTPException(status_code=404, detail="No active subscription")

        records = db.query(BillingRecord).filter(
            BillingRecord.subscription_id == sub.subscription_id,
            BillingRecord.status == "paid",
        ).all()

        total_revenue = sum(r.amount for r in records)
        
        from kite_app.saas_config import get_monthly_price
        monthly_price = get_monthly_price(org.subscription_tier)

        return {
            "org_id": org_id,
            "tier": org.subscription_tier,
            "monthly_price": monthly_price,
            "billing_cycle": sub.billing_cycle,
            "total_revenue": total_revenue,
            "total_invoices": len(records),
        }
    finally:
        db.close()


@router.get("/audit-logs/{org_id}")
def get_audit_logs(org_id: str, limit: int = 100) -> list:
    """Get audit logs for organization."""
    db = get_sessionmaker()()
    try:
        logs = db.query(AuditLog).filter(
            AuditLog.org_id == uuid.UUID(org_id)
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()

        return [
            {
                "log_id": str(log.log_id),
                "org_id": str(log.org_id),
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "details": log.details,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    finally:
        db.close()


@router.get("/organizations")
def list_all_organizations(limit: int = 50, offset: int = 0) -> dict:
    """List all organizations with pagination."""
    db = get_sessionmaker()()
    try:
        total = db.query(func.count(Organization.org_id)).scalar()
        orgs = db.query(Organization).limit(limit).offset(offset).all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "organizations": [
                {
                    "org_id": str(org.org_id),
                    "name": org.name,
                    "email": org.email,
                    "tier": org.subscription_tier,
                    "is_active": org.is_active,
                    "created_at": org.created_at.isoformat(),
                }
                for org in orgs
            ]
        }
    finally:
        db.close()
