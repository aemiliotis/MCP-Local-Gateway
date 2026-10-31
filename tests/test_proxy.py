"""
Tests for /v1/proxy (MCP gateway forwarding).

Note: the rate limiter is shared via Redis, so we clear it in conftest.py
before each test. These tests should therefore never see 429.
"""

import pytest


def test_proxy_missing_fields_returns_400(client, auth_headers):
    """POST /v1/proxy without server_slug or tool_name returns 400."""
    resp = client.post("/v1/proxy", json={}, headers=auth_headers)
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert "required" in resp.get_json()["error"]


def test_proxy_unknown_server_returns_404(client, auth_headers):
    """POST /v1/proxy with unknown server_slug returns 404."""
    resp = client.post(
        "/v1/proxy",
        json={"server_slug": "unknown", "tool_name": "x", "arguments": {}},
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == "server_not_found"


def test_proxy_budget_exceeded_returns_402(client, auth_headers):
    """POST /v1/proxy when cap is exceeded returns 402."""
    client.post(
        "/v1/policy",
        json={"session_id": "budget-test", "cap": 0.00001},
        headers=auth_headers,
    )

    resp = client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Athens"},
            "session_id": "budget-test",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 402, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == "budget_exceeded"


def test_proxy_upstream_error_returns_502(client, auth_headers):
    """POST /v1/proxy when upstream is unreachable returns 502."""
    resp = client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Athens"},
            "session_id": "upstream-test",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 502, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == "upstream_error"
