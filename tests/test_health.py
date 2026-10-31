"""
Tests for /v1/health and /api/health.
"""


def test_v1_health_returns_ok(client):
    """GET /v1/health must return 200 with status ok."""
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_api_health_returns_ok(client):
    """GET /api/health must return 200 with status ok."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
