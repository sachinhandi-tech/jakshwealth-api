"""Multi-tenant SaaS models for subscription management and admin controls."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum as SQLEnum, Integer, String, Text, Uuid, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from typing import Optional


class SaasBase(DeclarativeBase):
    """Metadata for SaaS tables."""


class SubscriptionTier(str, Enum):
    """Available subscription tiers."""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Organization(SaasBase):
    """Client organization/company in SaaS."""

    __tablename__ = "organizations"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)  # For white-label domain
    subscription_tier: Mapped[str] = mapped_column(SQLEnum(SubscriptionTier), default=SubscriptionTier.FREE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Subscription(SaasBase):
    """Subscription details for an organization."""

    __tablename__ = "subscriptions"

    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.org_id"), nullable=False)
    tier: Mapped[str] = mapped_column(SQLEnum(SubscriptionTier), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # active, cancelled, expired
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    billing_cycle: Mapped[str] = mapped_column(String(16), default="monthly")  # monthly or yearly
    next_billing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrganizationUser(SaasBase):
    """Users within an organization."""

    __tablename__ = "organization_users"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.org_id"), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # admin, member, viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)  # Links to jakshwealth users
    zerodha_user_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiKey(SaasBase):
    """API keys for programmatic access."""

    __tablename__ = "api_keys"

    key_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.org_id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organization_users.user_id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # SHA256 hash
    name: Mapped[str] = mapped_column(String(128), nullable=False)  # Friendly name
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageMetrics(SaasBase):
    """Track API usage per organization for quota management."""

    __tablename__ = "usage_metrics"

    metric_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.org_id"), nullable=False)
    period_date: Mapped[date] = mapped_column(Date, nullable=False)  # YYYY-MM-DD
    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    signal_scans: Mapped[int] = mapped_column(Integer, default=0)
    nifty100_scans: Mapped[int] = mapped_column(Integer, default=0)
    all_nse_scans: Mapped[int] = mapped_column(Integer, default=0)
    trades_created: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLog(SaasBase):
    """Audit trail of admin actions and important events."""

    __tablename__ = "audit_logs"

    log_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.org_id"), nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)  # Who did it
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # user_created, subscription_upgraded, etc
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)  # user, subscription, api_key, etc
    resource_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # ID of affected resource
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Extra context
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BillingRecord(SaasBase):
    """Billing and payment records."""

    __tablename__ = "billing_records"

    billing_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.org_id"), nullable=False)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.subscription_id"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    amount: Mapped[float] = mapped_column(nullable=False)  # In rupees/dollars
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    billing_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    billing_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # draft, sent, paid, overdue, cancelled
    payment_method: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # card, bank_transfer, etc
    payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)


class WhiteLabel(SaasBase):
    """White-label branding settings per organization."""

    __tablename__ = "white_labels"

    label_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.org_id"), nullable=False)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    logo_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    primary_color: Mapped[str] = mapped_column(String(7), default="#00d4ff")  # Hex color
    secondary_color: Mapped[str] = mapped_column(String(7), default="#1a1a2e")
    custom_domain: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)  # e.g., app.clientname.com
    support_email: Mapped[str] = mapped_column(String(320), nullable=False)
    privacy_policy_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    terms_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
