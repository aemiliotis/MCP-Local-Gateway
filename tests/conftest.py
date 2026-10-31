
"""
Pytest fixtures for MCP Local Gateway tests.

Clears the Redis rate limiter before and after each test so that
tests do not interfere with each other via the shared 100/hour limit.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def valid_api_key():
    """Use the built-in test key that exists in app.py when TESTING=1."""
    return "test-key-123"


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    """Clear Redis rate limiter keys before and after each test."""
    def _flush():
        try:
            import redis
            r = redis.Redis(host="localhost", port=6379, db=0)
            r.flushdb()
        except Exception:
            pass

    _flush()
    yield
    _flush()


@pytest.fixture(scope="function")
def app(monkeypatch, tmp_path):
    """Create a Flask app with temporary DBs and TESTING=1."""
    api_db = tmp_path / "test_api.db"
    gateway_db = tmp_path / "test_gateway.db"

    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("API_DB", str(api_db))
    monkeypatch.setenv("GATEWAY_DB", str(gateway_db))
    monkeypatch.setenv("MCP_SERVERS_JSON", '{"weather": "http://127.0.0.1:9999"}')

    for mod_name in list(sys.modules.keys()):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]

    import app as app_module
    app_module.app.config["TESTING"] = True

    yield app_module.app

    for mod_name in list(sys.modules.keys()):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]


@pytest.fixture(scope="function")
def client(app):
    return app.test_client()


@pytest.fixture(scope="function")
def auth_headers(valid_api_key):
    return {
        "X-API-Key": valid_api_key,
        "Content-Type": "application/json",
    }


@pytest.fixture(scope="function")
def no_auth_headers():
    return {"Content-Type": "application/json"}
