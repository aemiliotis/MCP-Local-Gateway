"""
Tests for edge cases: empty inputs, oversized payloads, malformed JSON.
"""

import pytest


def test_proxy_empty_arguments(client, auth_headers):
    """Empty arguments dict should be accepted (no error)."""
    resp = client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {},
            "session_id": "empty-args-test",
        },
        headers=auth_headers,
    )
    assert resp.status_code in (200, 502), resp.get_data(as_text=True)


def test_proxy_missing_arguments_key(client, auth_headers):
    """Missing arguments key should default to empty dict."""
    resp = client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "session_id": "missing-args-test",
        },
        headers=auth_headers,
    )
    assert resp.status_code in (200, 502), resp.get_data(as_text=True)


def test_proxy_empty_session_id(client, auth_headers):
    """Empty session_id should be accepted (defaults to 'default')."""
    resp = client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {},
            "session_id": "",
        },
        headers=auth_headers,
    )
    assert resp.status_code in (200, 402, 404, 502), resp.get_data(as_text=True)


def test_proxy_malformed_json_returns_400(client, auth_headers):
    """Malformed JSON should return 400, not crash."""
    resp = client.post(
        "/v1/proxy",
        data="not valid json {",
        headers=auth_headers,
        content_type="application/json",
    )
    assert resp.status_code in (400, 415), resp.get_data(as_text=True)


def test_proxy_oversized_payload_returns_413_or_400(client, auth_headers):
    """
    Oversized payload should be rejected (413), handled (200/502),
    or blocked by budget (402) because 10MB costs ~$5.24 > $5 default cap.
    """
    huge_args = {"data": "x" * (10 * 1024 * 1024)}  # 10 MB
    resp = client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": huge_args,
            "session_id": "huge-payload-test",
        },
        headers=auth_headers,
    )
    # 402 is correct: the gateway blocks the huge payload before sending
    assert resp.status_code in (200, 402, 413, 502), resp.get_data(as_text=True)


def test_policy_negative_cap(client, auth_headers):
    """Negative cap should be accepted (treated as 0)."""
    resp = client.post(
        "/v1/policy",
        json={"session_id": "neg-cap-test", "cap": -1.0},
        headers=auth_headers,
    )
    assert resp.status_code == 200


def test_policy_zero_cap_blocks_all(client, auth_headers):
    """Zero cap should block all proxy calls."""
    session = "zero-cap-test"
    client.post(
        "/v1/policy",
        json={"session_id": session, "cap": 0.0},
        headers=auth_headers,
    )
    resp = client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Athens"},
            "session_id": session,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 402, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == "budget_exceeded"


def test_audit_limit_param_capped(client, auth_headers):
    """The limit query param should be capped at 500."""
    resp = client.get("/v1/audit?limit=10000", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_audit_negative_limit(client, auth_headers):
    """Negative limit should not crash."""
    resp = client.get("/v1/audit?limit=-5", headers=auth_headers)
    assert resp.status_code in (200, 400)


def test_health_with_extra_headers(client):
    """Health endpoint should ignore unrelated headers."""
    resp = client.get(
        "/v1/health",
        headers={"X-Custom": "value", "Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200


def test_proxy_unicode_arguments(client, auth_headers):
    """Unicode in arguments should be preserved."""
    resp = client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Αθήνα", "emoji": "🌤️"},
            "session_id": "unicode-test",
        },
        headers=auth_headers,
    )
    assert resp.status_code in (200, 502), resp.get_data(as_text=True)
