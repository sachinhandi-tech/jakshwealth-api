import pytest
from fastapi import HTTPException

from kite_app.main import saas_router as included_admin
from kite_app.main import subscription_router as included_subscriptions
from kite_app.saas_router import get_current_user_org
from kite_app.saas_router import router as admin_router
from kite_app.saas_subscription import router as subscription_router


def test_admin_account_requires_the_desk_user():
    with pytest.raises(HTTPException) as caught:
        get_current_user_org(None)
    assert caught.value.status_code == 401
    assert caught.value.detail == "Platform user ID required"


def test_subscription_and_member_routes_match_the_desk():
    assert included_admin is admin_router
    assert included_subscriptions is subscription_router
    admin_paths = {(route.path, frozenset(route.methods)) for route in admin_router.routes}
    subscription_paths = {route.path for route in subscription_router.routes}
    assert ("/api/admin/organizations/{org_id}/users/{user_id}", frozenset({"DELETE"})) in admin_paths
    assert "/api/subscriptions/organizations/{org_id}/subscription" in subscription_paths
    assert "/api/subscriptions/organizations/{org_id}/upgrade" in subscription_paths
