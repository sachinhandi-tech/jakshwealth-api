"""Secure-data feature subroutes.

Add a new feature by creating ``features/<name>/`` and appending its ``ROUTE``
to ``FEATURE_ROUTES`` below.
"""

from features.admin import FEATURES_ROUTE as admin_features_route
from features.admin import ROUTE as admin_route
from features.ai_chat import ROUTE as ai_chat_route
from features.fetch_charts import ROUTE as fetch_charts_route
from features.stock_scan.handler import ROUTE as stock_scan_route
from features.stock_scan.handler import UNIVERSE_ROUTE as stock_universe_route
from routing import FeatureRoute

FEATURE_ROUTES: tuple[FeatureRoute, ...] = (
    admin_route,
    admin_features_route,
    ai_chat_route,
    fetch_charts_route,
    stock_scan_route,
    stock_universe_route,
)

__all__ = ["FEATURE_ROUTES"]
