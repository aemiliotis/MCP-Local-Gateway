"""
Tests for rate limiting on /v1/proxy.

The gateway is configured with @limiter.limit("100 per hour").
These tests verify that the 101st request returns 429.

Note: each test uses a fresh app (via conftest) and the Redis limiter
is cleared before each test, so the 100/hour bucket starts empty.
"""

import pytest


@pytest.fixture(scope="function")
def auth_headers():
    return {
        "X-API-Key": "test-key-123",
        "Content-Type": "application/json",
    }


def test_rate_limit_exceeded_returns_429(client, auth_headers):
    """After 100 requests in an hour, the 101st returns 429."""
    # The rate limit is 100/hour for /v1/proxy.
    for i in range(100):
        resp = client.post(
            "/v1/proxy",
            json={
                "server_slug": "weather",
                "tool_name": "get_forecast",
                "arguments": {"city": f"City{i}"},
                "session_id": f"rate-test-{i}",
            },
            headers=auth_headers,
        )
        # Allow 200/402/404/502 — all count toward the rate limit
        assert resp.status_code in (200, 402, 404, 502), (
            f"Request {i} returned {resp.status_code}: {resp.get_data(as_text=True)}"
        )

    # The 101st request should be rate-limited
    resp = client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Overflow"},
            "session_id": "rate-test-overflow",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 429
    data = resp.get_json()
    assert data["error"] == "rate_limit_exceeded"


def test_rate_limit_does_not_affect_health(client, auth_headers):
    """Rate limiting on /v1/proxy should not affect /v1/health."""
    # Exhaust the rate limit
    for i in range(101):
        client.post(
            "/v1/proxy",
            json={"server_slug": "x", "tool_name": "y", "arguments": {}},
            headers=auth_headers,
        )

    # Health should still work
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
