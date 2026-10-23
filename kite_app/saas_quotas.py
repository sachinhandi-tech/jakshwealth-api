"""Rate limiting and quota management for SaaS."""

from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from kite_app.saas_models import Organization, UsageMetrics, Subscription
from kite_app.saas_auth import TenantContext
from kite_app.saas_config import get_tier_config
from kite_app.models import get_sessionmaker


class QuotaChecker:
    """Check and enforce quotas for organization."""

    def __init__(self, context: TenantContext, db: Session):
        self.context = context
        self.db = db
        self.org = self.db.query(Organization).filter(
            Organization.org_id == context.org_id
        ).first()
        
        if not self.org:
            raise HTTPException(status_code=404, detail="Organization not found")

    def get_tier_config(self) -> dict:
        """Get tier configuration."""
        return get_tier_config(self.org.subscription_tier)

    def get_today_metrics(self) -> UsageMetrics:
        """Get or create today's usage metrics."""
        today = date.today()
        metrics = self.db.query(UsageMetrics).filter(
            UsageMetrics.org_id == self.context.org_id,
            UsageMetrics.period_date == today,
        ).first()

        if not metrics:
            metrics = UsageMetrics(
                metric_id=uuid.uuid4(),
                org_id=self.context.org_id,
                period_date=today,
                created_at=datetime.now(),
            )
            self.db.add(metrics)
            self.db.commit()

        return metrics

    def get_month_metrics(self) -> UsageMetrics:
        """Get aggregated metrics for current month."""
        today = date.today()
        month_start = date(today.year, today.month, 1)
        
        daily_metrics = self.db.query(UsageMetrics).filter(
            UsageMetrics.org_id == self.context.org_id,
            UsageMetrics.period_date >= month_start,
            UsageMetrics.period_date <= today,
        ).all()

        # Aggregate
        agg = UsageMetrics(
            org_id=self.context.org_id,
            period_date=today,
        )
        for m in daily_metrics:
            agg.api_calls += m.api_calls
            agg.signal_scans += m.signal_scans
            agg.nifty100_scans += m.nifty100_scans
            agg.all_nse_scans += m.all_nse_scans
            agg.trades_created += m.trades_created

        return agg

    def check_scan_quota(self, scan_type: str = "nifty100_short_term") -> None:
        """Check if organization can perform a scan."""
        config = self.get_tier_config()
        max_scans = config["max_scans_per_month"]

        # Check if tier allows this scan type
        if scan_type not in config["scan_types"]:
            raise HTTPException(
                status_code=403,
                detail=f"Tier {self.org.subscription_tier} does not support {scan_type} scans"
            )

        # Check monthly quota
        if max_scans != float("inf"):
            month_metrics = self.get_month_metrics()
            total_scans = month_metrics.signal_scans
            
            if total_scans >= max_scans:
                raise HTTPException(
                    status_code=429,
                    detail=f"Monthly scan quota exceeded ({total_scans}/{max_scans})"
                )

    def check_api_quota(self) -> None:
        """Check if organization can make API calls."""
        config = self.get_tier_config()
        max_calls = config["max_api_calls_per_month"]

        if max_calls == float("inf"):
            return

        month_metrics = self.get_month_metrics()
        if month_metrics.api_calls >= max_calls:
            raise HTTPException(
                status_code=429,
                detail=f"Monthly API call quota exceeded ({month_metrics.api_calls}/{max_calls})"
            )

    def increment_scans(self, scan_type: str = "nifty100_short_term", count: int = 1) -> None:
        """Increment scan counter."""
        metrics = self.get_today_metrics()
        metrics.signal_scans += count

        if scan_type == "nifty100_short_term" or scan_type == "nifty100_long_term":
            metrics.nifty100_scans += count
        elif scan_type == "all_nse_short_term" or scan_type == "all_nse_long_term":
            metrics.all_nse_scans += count

        self.db.commit()

    def increment_api_calls(self, count: int = 1) -> None:
        """Increment API call counter."""
        metrics = self.get_today_metrics()
        metrics.api_calls += count
        self.db.commit()

    def increment_trades(self, count: int = 1) -> None:
        """Increment trade counter."""
        metrics = self.get_today_metrics()
        metrics.trades_created += count
        self.db.commit()

    def get_usage_summary(self) -> dict:
        """Get usage summary for organization."""
        config = self.get_tier_config()
        month_metrics = self.get_month_metrics()

        return {
            "tier": self.org.subscription_tier,
            "month": date.today().isoformat(),
            "api_calls": {
                "used": month_metrics.api_calls,
                "limit": config["max_api_calls_per_month"],
                "percentage": (month_metrics.api_calls / config["max_api_calls_per_month"] * 100)
                    if config["max_api_calls_per_month"] != float("inf") else 0,
            },
            "scans": {
                "used": month_metrics.signal_scans,
                "limit": config["max_scans_per_month"],
                "percentage": (month_metrics.signal_scans / config["max_scans_per_month"] * 100)
                    if config["max_scans_per_month"] != float("inf") else 0,
            },
            "trades": {
                "created": month_metrics.trades_created,
            },
        }
