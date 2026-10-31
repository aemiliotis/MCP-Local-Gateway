"""
Tests for /v1/policy (budget cap management).
"""


def test_set_policy_returns_cap(client, auth_headers):
    """POST /v1/policy sets cap and returns it."""
    resp = client.post(
        "/v1/policy",
        json={"session_id": "policy-test", "cap": 2.50},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["session_id"] == "policy-test"
    assert data["cap"] == 2.50
    assert data["tenant"] == "tenant-1"


def test_set_policy_default_cap(client, auth_headers):
    """POST /v1/policy without cap uses default."""
    resp = client.post(
        "/v1/policy",
        json={"session_id": "default-cap-test"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.get_json()["cap"] == 5.00
