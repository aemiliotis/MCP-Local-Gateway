"""
Integration tests with a real mock MCP server.

Starts a real HTTP server in a background thread, configures the gateway
to point to it, and verifies the full proxy flow end-to-end.

The assertions are intentionally tolerant of the gateway's response
envelope: the upstream mock payload may be returned directly, or nested
under a key such as "result", "data", "upstream", etc. We search for it.
"""

import sys
import threading
import time

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server


class MockMCPServer:
    """A real HTTP server that mimics an MCP server."""

    def __init__(self):
        self.app = Flask("mock_mcp")
        self._setup_routes()
        self.server = None
        self.thread = None
        self.port = None

    def _setup_routes(self):
        @self.app.route("/tools/<tool_name>", methods=["POST"])
        def tool(tool_name):
            args = request.get_json() or {}
            return jsonify({
                "tool": tool_name,
                "args": args,
                "result": f"mock result for {tool_name}",
            })

    def start(self):
        self.server = make_server("127.0.0.1", 0, self.app)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        time.sleep(0.5)

    def stop(self):
        if self.server:
            self.server.shutdown()
        if self.thread:
            self.thread.join(timeout=2)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


def _find_upstream_payload(body):
    """
    Locate the upstream MCP payload inside the gateway response envelope.

    Tries the common envelopes first, then falls back to a recursive search
    for a dict that contains both "tool" and "result" keys (the signature
    of our mock MCP server's response).
    """
    if not isinstance(body, dict):
        return None

    # Direct (gateway returned the upstream JSON verbatim)
    if "tool" in body and "result" in body:
        return body

    # Common envelope keys
    for key in ("result", "data", "upstream", "response", "payload", "body"):
        candidate = body.get(key)
        if isinstance(candidate, dict) and "tool" in candidate and "result" in candidate:
            return candidate

    # Recursive fallback
    for value in body.values():
        found = _find_upstream_payload(value)
        if found is not None:
            return found

    return None


@pytest.fixture(scope="function")
def mock_mcp_server():
    server = MockMCPServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="function")
def app_with_mock_mcp(monkeypatch, tmp_path, mock_mcp_server):
    api_db = tmp_path / "test_api.db"
    gateway_db = tmp_path / "test_gateway.db"

    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("API_DB", str(api_db))
    monkeypatch.setenv("GATEWAY_DB", str(gateway_db))
    monkeypatch.setenv(
        "MCP_SERVERS_JSON",
        f'{{"weather": "{mock_mcp_server.url}"}}',
    )

    for mod_name in list(sys.modules.keys()):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]

    import app as app_module
    app_module.app.config["TESTING"] = True

    yield app_module.app

    for mod_name in list(sys.modules.keys()):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]


# ---------------------------------------------------------------------------
# Integration tests (happy path) — use the real mock MCP server
# ---------------------------------------------------------------------------

def test_integration_proxy_happy_path(app_with_mock_mcp, auth_headers):
    """Full proxy flow: gateway -> real mock MCP server -> response."""
    client = app_with_mock_mcp.test_client()
    resp = client.post(
        "/v1/proxy",
        headers=auth_headers,
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Athens"},
            "session_id": "sess-integration-1",
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body is not None, "Expected a JSON body"

    upstream = _find_upstream_payload(body)
    assert upstream is not None, (
        "Could not locate upstream payload inside gateway response. "
        f"Actual body: {body!r}"
    )
    assert upstream["tool"] == "get_forecast"
    assert upstream["args"] == {"city": "Athens"}
    assert "mock result for get_forecast" in upstream["result"]


def test_integration_proxy_passes_arguments(app_with_mock_mcp, auth_headers):
    """Arguments must be forwarded verbatim to the upstream MCP server."""
    client = app_with_mock_mcp.test_client()
    resp = client.post(
        "/v1/proxy",
        headers=auth_headers,
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Thessaloniki", "days": 3},
            "session_id": "sess-integration-2",
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    upstream = _find_upstream_payload(body)
    assert upstream is not None, (
        "Could not locate upstream payload inside gateway response. "
        f"Actual body: {body!r}"
    )
    assert upstream["args"] == {"city": "Thessaloniki", "days": 3}


def test_integration_audit_records_call(app_with_mock_mcp, auth_headers):
    """A successful proxy call must appear in the audit log."""
    client = app_with_mock_mcp.test_client()

    # Make one proxy call
    proxy_resp = client.post(
        "/v1/proxy",
        headers=auth_headers,
        json={
            "server_slug": "weather",
            "tool_name": "get_forecast",
            "arguments": {"city": "Patras"},
            "session_id": "sess-integration-audit",
        },
    )
    assert proxy_resp.status_code == 200

    # Then read the audit log
    audit_resp = client.get("/v1/audit", headers=auth_headers)
    assert audit_resp.status_code == 200
    entries = audit_resp.get_json()
    assert isinstance(entries, list)
    assert any(
        e.get("tool_name") == "get_forecast"
        and e.get("server_slug") == "weather"
        for e in entries
    ), f"Expected get_forecast entry, got: {entries}"
