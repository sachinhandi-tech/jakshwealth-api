from features import FEATURE_ROUTES


def test_feature_routes_are_registered():
    paths = {route.path for route in FEATURE_ROUTES}
    assert paths == {
        "admin",
        "admin/features",
        "ai-chat",
        "fetch-charts",
        "stock-scan",
        "stock-universe",
    }
