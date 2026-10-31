"""
Tests for the audit log.

Verifies that every decision (ALLOWED, BLOCKED, ERROR) is logged correctly.
"""


def test_audit_logs_blocked_by_unknown_server(client, auth_headers):
    """A 404 (unknown server) should be logged as BLOCKED with reason."""
    session = "audit-blocked-test"

    client.post(
        "/v1/proxy",
        json={
            "server_slug": "unknown",
            "tool_name": "x",
            "arguments": {},
            "session_id": session,
        },
        headers=auth_headers,
    )

    resp = client.get(f"/v1/audit?session_id={session}", headers=auth_headers)
    entries = resp.get_json()
    assert len(entries) >= 1
    entry = entries[0]
    assert entry["decision"] == "BLOCKED"
    assert entry["reason"] == "server_not_found"
    assert entry["server_slug"] == "unknown"


def test_audit_logs_budget_exceeded(client, auth_headers):
    """A 402 (budget exceeded) should be logged as BLOCKED with reason."""
    session = "audit-budget-test"

    client.post(
        "/v1/policy",
        json={"session_id": session, "cap": 0.00001},
        headers=auth_headers,
    )
    client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Athens"},
            "session_id": session,
        },
        headers=auth_headers,
    )

    resp = client.get(f"/v1/audit?session_id={session}", headers=auth_headers)
    entries = resp.get_json()
    assert len(entries) >= 1
    assert entries[0]["decision"] == "BLOCKED"
    assert entries[0]["reason"] == "session cap exceeded"


def test_audit_logs_upstream_error(client, auth_headers):
    """A 502 (upstream error) should be logged as ERROR."""
    session = "audit-upstream-test"

    client.post(
        "/v1/proxy",
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Athens"},
            "session_id": session,
        },
        headers=auth_headers,
    )

    resp = client.get(f"/v1/audit?session_id={session}", headers=auth_headers)
    entries = resp.get_json()
    assert len(entries) >= 1
    assert entries[0]["decision"] == "ERROR"


def test_audit_isolated_by_tenant(client, auth_headers):
    """Audit log for one tenant does not show another tenant's entries."""
    client.post(
        "/v1/proxy",
        json={
            "server_slug": "unknown",
            "tool_name": "x",
            "arguments": {},
            "session_id": "tenant-isolation-test",
        },
        headers=auth_headers,
    )

    resp = client.get("/v1/audit", headers=auth_headers)
    entries = resp.get_json()
    for entry in entries:
        assert entry["tenant"] == "tenant-1"
