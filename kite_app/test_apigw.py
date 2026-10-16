from kite_app.apigw import normalize_event, normalize_path


def test_normalize_path_strips_the_gateway_prefix():
    assert normalize_path("/jw-api/kite/api/kite/session") == "/api/kite/session"
    assert normalize_path("/dev/jw-api/kite/api/kite/login") == "/api/kite/login"
    assert normalize_path("/jw-api/kite") == "/"


def test_normalize_event_updates_rest_and_http_api_paths():
    event = {
        "path": "/jw-api/kite/api/kite/profile",
        "requestContext": {"http": {"path": "/jw-api/kite/api/kite/profile"}},
    }
    normalized = normalize_event(event)
    assert normalized["path"] == "/api/kite/profile"
    assert normalized["requestContext"]["http"]["path"] == "/api/kite/profile"
