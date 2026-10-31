"""
Tests for API key authentication.
"""


def test_proxy_without_api_key_returns_401(client, no_auth_headers):
    """POST /v1/proxy without X-API-Key must return 401."""
    resp = client.post(
        "/v1/proxy",
        json={"server_slug": "weather", "tool_name": "get_forecast"},
        headers=no_auth_headers,
    )
    assert resp.status_code == 401
    data = resp.get_json()
    assert data["error"] == "unauthorized"


def test_proxy_with_wrong_api_key_returns_401(client):
    """POST /v1/proxy with wrong X-API-Key must return 401."""
    resp = client.post(
        "/v1/proxy",
        json={"server_slug": "weather", "tool_name": "get_forecast"},
        headers={"X-API-Key": "wrong-key", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_policy_without_api_key_returns_401(client, no_auth_headers):
    """POST /v1/policy without X-API-Key must return 401."""
    resp = client.post(
        "/v1/policy",
        json={"session_id": "s1", "cap": 1.0},
        headers=no_auth_headers,
    )
    assert resp.status_code == 401


def test_audit_without_api_key_returns_401(client, no_auth_headers):
    """GET /v1/audit without X-API-Key must return 401."""
    resp = client.get("/v1/audit", headers=no_auth_headers)
    assert resp.status_code == 401
