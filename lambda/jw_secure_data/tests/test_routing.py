from features import FEATURE_ROUTES


def test_feature_routes_are_registered():
    paths = {route.path for route in FEATURE_ROUTES if not route.path_prefix}
    prefixes = {route.path_prefix for route in FEATURE_ROUTES if route.path_prefix}
    assert paths == {
        "admin",
        "admin/features",
        "ai-chat",
        "fetch-charts",
        "stock-scan",
        "stock-scan/async",
        "stock-universe",
    }
    assert prefixes == {"stock-scan/jobs/"}


def test_job_route_matches_dynamic_suffix():
    job_route = next(route for route in FEATURE_ROUTES if route.path_prefix == "stock-scan/jobs/")
    assert job_route.matches("stock-scan/jobs/abc-123")
    assert not job_route.matches("stock-scan/jobs/")
    assert not job_route.matches("stock-scan/async")
