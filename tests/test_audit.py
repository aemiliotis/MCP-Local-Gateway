"""
Tests for /v1/audit (audit log retrieval).
"""


def test_audit_empty_returns_list(client, auth_headers):
    """GET /v1/audit with no entries returns empty list."""
    resp = client.get("/v1/audit", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_audit_after_proxy_call(client, auth_headers):
    """GET /v1/audit returns entries after a proxy call."""
    # Make a proxy call (will fail upstream, but audit is logged)
    client.post(
        "/v1/proxy",
        json={
            "server_slug": "unknown",
            "tool_name": "x",
            "arguments": {},
            "session_id": "audit-test",
        },
        headers=auth_headers,
    )

    resp = client.get("/v1/audit?session_id=audit-test", headers=auth_headers)
    assert resp.status_code == 200
    entries = resp.get_json()
    assert len(entries) >= 1
    assert entries[0]["session_id"] == "audit-test"
    assert entries[0]["decision"] in ("ALLOWED", "BLOCKED", "ERROR", "UPSTREAM_ERROR")
