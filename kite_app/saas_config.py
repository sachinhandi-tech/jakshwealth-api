"""Subscription tier definitions and feature access matrix."""

from typing import Dict, Any


TIER_LIMITS = {
    "free": {
        "max_users": 1,
        "max_api_calls_per_month": 1000,
        "max_scans_per_month": 100,
        "scan_types": ["nifty100_short_term"],  # Only short-term Nifty 100
        "features": ["signal_scanning", "dashboard"],
        "api_access": False,
        "white_label": False,
        "support": "community",
    },
    "pro": {
        "max_users": 10,
        "max_api_calls_per_month": 50000,
        "max_scans_per_month": 1000,
        "scan_types": ["nifty100_short_term", "nifty100_long_term"],  # Nifty 100 both terms
        "features": ["signal_scanning", "dashboard", "trade_tracking", "performance_analytics"],
        "api_access": True,
        "white_label": False,
        "support": "email",
        "monthly_price": 499,  # INR
    },
    "enterprise": {
        "max_users": float("inf"),
        "max_api_calls_per_month": float("inf"),
        "max_scans_per_month": float("inf"),
        "scan_types": ["nifty100_short_term", "nifty100_long_term", "all_nse_short_term", "all_nse_long_term"],
        "features": ["signal_scanning", "dashboard", "trade_tracking", "performance_analytics", "custom_strategies"],
        "api_access": True,
        "white_label": True,
        "support": "priority",
        "monthly_price": 9999,  # INR, custom for enterprise
    },
}


def get_tier_config(tier: str) -> Dict[str, Any]:
    """Get configuration for a subscription tier."""
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])


def can_scan_all_nse(tier: str) -> bool:
    """Check if tier allows all NSE scanning."""
    config = get_tier_config(tier)
    return any("all_nse" in s for s in config["scan_types"])


def can_use_api(tier: str) -> bool:
    """Check if tier has API access."""
    return get_tier_config(tier)["api_access"]


def has_white_label(tier: str) -> bool:
    """Check if tier supports white-label."""
    return get_tier_config(tier)["white_label"]


def get_max_users(tier: str) -> int | float:
    """Get max users allowed for tier."""
    return get_tier_config(tier)["max_users"]


def get_monthly_price(tier: str) -> float:
    """Get monthly price for tier."""
    return get_tier_config(tier).get("monthly_price", 0)
