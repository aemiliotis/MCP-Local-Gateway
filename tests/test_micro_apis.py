"""
Tests for micro-APIs (/api/*).
"""

import base64


def test_qr_returns_png(client):
    """POST /api/qr returns a PNG image."""
    resp = client.post("/api/qr", json={"text": "hello"})
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


def test_qr_missing_text_returns_400(client):
    """POST /api/qr without text returns 400."""
    resp = client.post("/api/qr", json={})
    assert resp.status_code == 400


def test_hash_and_verify(client):
    """POST /api/hash then /api/verify-hash roundtrip."""
    resp = client.post("/api/hash", json={"text": "secret"})
    assert resp.status_code == 200
    hashed = resp.get_json()["hash"]

    resp = client.post("/api/verify-hash", json={"text": "secret", "hash": hashed})
    assert resp.status_code == 200
    assert resp.get_json()["match"] is True

    resp = client.post("/api/verify-hash", json={"text": "wrong", "hash": hashed})
    assert resp.get_json()["match"] is False


def test_uuid_returns_requested_count(client):
    """POST /api/uuid returns the requested number of UUIDs."""
    resp = client.post("/api/uuid", json={"count": 3})
    assert resp.status_code == 200
    uuids = resp.get_json()["uuids"]
    assert len(uuids) == 3
    assert all(len(u) == 36 for u in uuids)


def test_random_returns_requested_length(client):
    """POST /api/random returns a string of requested length."""
    resp = client.post("/api/random", json={"length": 16, "charset": "hex"})
    assert resp.status_code == 200
    value = resp.get_json()["value"]
    assert len(value) == 16
    assert all(c in "0123456789abcdef" for c in value)


def test_base64_encode_decode(client):
    """POST /api/base64 encode and decode roundtrip."""
    resp = client.post("/api/base64", json={"op": "encode", "text": "hello"})
    assert resp.status_code == 200
    encoded = resp.get_json()["result"]
    assert encoded == base64.b64encode(b"hello").decode()

    resp = client.post("/api/base64", json={"op": "decode", "text": encoded})
    assert resp.get_json()["result"] == "hello"


def test_vat_calculation(client):
    """POST /api/vat computes VAT correctly."""
    resp = client.post("/api/vat", json={"amount": 100, "rate": 24})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["vat"] == 24.0
    assert data["total"] == 124.0


def test_card_validate_visa(client):
    """POST /api/card-validate recognises a valid Visa number."""
    resp = client.post("/api/card-validate", json={"number": "4111111111111111"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is True
    assert data["type"] == "visa"


def test_password_strength(client):
    """POST /api/password-strength returns score and label."""
    resp = client.post("/api/password-strength", json={"password": "Abc123!xyz"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert 0 <= data["score"] <= 5
    assert data["label"] in (
        "very weak", "weak", "fair", "good", "strong", "very strong"
    )
