from ec2_host.lambda_adapter import apply_lambda_result, build_lambda_event


def test_build_event_keeps_the_secure_data_path_and_query():
    event = build_lambda_event(
        "POST",
        "/jw-api/secure-data/stocks?limit=2",
        {"Content-Type": "application/json"},
        b'{"symbol":"INFY"}',
    )
    assert event["httpMethod"] == "POST"
    assert event["path"] == "/jw-api/secure-data/stocks"
    assert event["queryStringParameters"] == {"limit": "2"}
    assert event["body"] == '{"symbol":"INFY"}'
    assert event["requestContext"]["authorizer"] == {}


def test_apply_result_writes_the_lambda_status_and_body():
    def handler(event, context):
        assert context is None
        return {"statusCode": 201, "headers": {"Content-Type": "application/json"}, "body": '{"ok":true}'}

    status, headers, payload = apply_lambda_result(handler, {})
    assert status == 201
    assert ("Content-Type", "application/json") in headers
    assert payload == b'{"ok":true}'
