"""
MCP Local Gateway
A self-hosted governance layer for MCP servers:
API key auth, Redis-backed rate limiting, cost estimation,
budget caps, trust checks, and audit logging.

Author: aemiliotis
License: MIT
"""

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone as dt_timezone

import bcrypt
import pyotp
import requests
from croniter import croniter
from flask import Flask, jsonify, redirect, request, send_file
from flask_limiter import Limiter
from flask_limiter.errors import RateLimitExceeded
from flask_limiter.util import get_remote_address
import io
import qrcode

# ------------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

API_DB = os.environ.get("API_DB", os.path.join(BASE_DIR, "api.db"))
GATEWAY_DB = os.environ.get("GATEWAY_DB", os.path.join(BASE_DIR, "gateway.db"))

TRUST_THRESHOLD = os.environ.get("TRUST_THRESHOLD", "C")
DEFAULT_SESSION_CAP = float(os.environ.get("DEFAULT_SESSION_CAP", "5.00"))
COST_PER_1K_TOKENS = float(os.environ.get("COST_PER_1K_TOKENS", "0.002"))
TOKENS_PER_ARG_BYTE = float(os.environ.get("TOKENS_PER_ARG_BYTE", "0.25"))
MCP_TRUST_API = os.environ.get("MCP_TRUST_API", "http://127.0.0.1:8000")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# MCP servers: slug -> base URL. Override via MCP_SERVERS_JSON.
_default_servers = {
    "weather": "http://127.0.0.1:9001",
    "database": "http://127.0.0.1:9002",
}
MCP_SERVERS = json.loads(
    os.environ.get("MCP_SERVERS_JSON", json.dumps(_default_servers))
)

# API keys: sha256(raw_key) -> tenant name.
# Empty by default. Override via API_KEYS_JSON.
VALID_KEY_HASHES = json.loads(os.environ.get("API_KEYS_JSON", "{}"))

# Test keys are ONLY added when TESTING=1 is set.
# NEVER set TESTING=1 in production.
if os.environ.get("TESTING") == "1":
    _TEST_KEYS = {
        hashlib.sha256(b"test-key-123").hexdigest(): "tenant-1",
        hashlib.sha256(b"test-key-456").hexdigest(): "tenant-2",
    }
    for _h, _t in _TEST_KEYS.items():
        VALID_KEY_HASHES.setdefault(_h, _t)

app = Flask(__name__)

# Max request body size (DoS protection). Default 1 MB.
app.config["MAX_CONTENT_LENGTH"] = int(
    os.environ.get("MAX_CONTENT_LENGTH", str(1 * 1024 * 1024))
)


# ------------------------------------------------------------------
# Rate limiter (Redis with graceful fallback to memory)
# ------------------------------------------------------------------
def _redis_available():
    try:
        import redis
        r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


STORAGE_URI = REDIS_URL if _redis_available() else "memory://"
app.logger.warning("Rate limiter storage: %s", STORAGE_URI)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=STORAGE_URI,
)


@app.errorhandler(RateLimitExceeded)
def handle_rate_limit(e):
    return jsonify({"error": "rate_limit_exceeded", "message": str(e.description)}), 429


# ------------------------------------------------------------------
# Database bootstrap (runs at import, so Gunicorn workers are ready)
# ------------------------------------------------------------------
def init_api_db():
    with sqlite3.connect(API_DB) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS links ("
            "code TEXT PRIMARY KEY, url TEXT, expires INTEGER)"
        )


def init_gateway_db():
    with sqlite3.connect(GATEWAY_DB) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                tenant TEXT,
                total_spent REAL DEFAULT 0,
                cap REAL DEFAULT 5.00,
                created_at INTEGER
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER,
                tenant TEXT,
                session_id TEXT,
                server_slug TEXT,
                tool_name TEXT,
                arguments TEXT,
                estimated_cost REAL,
                trust_grade TEXT,
                decision TEXT,
                reason TEXT
            )
        """)


init_api_db()
init_gateway_db()


def err(msg, code=400):
    return jsonify({"error": msg}), code


# ==================================================================
#  MICRO-APIs
# ==================================================================

@app.route("/api/shorten", methods=["POST"])
def shorten():
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    if not url or not re.match(r"^https?://", url):
        return err("url required (http/https)")
    ttl = int(data.get("ttl", 86400))
    code = data.get("slug") or secrets.token_urlsafe(6)
    expires = int(time.time()) + ttl
    with sqlite3.connect(API_DB) as c:
        try:
            c.execute("INSERT INTO links VALUES (?, ?, ?)", (code, url, expires))
        except sqlite3.IntegrityError:
            return err("slug already exists", 409)
    return jsonify({"short": f"/s/{code}", "expires_at": expires})


@app.route("/s/<code>")
def resolve(code):
    with sqlite3.connect(API_DB) as c:
        row = c.execute(
            "SELECT url, expires FROM links WHERE code=?", (code,)
        ).fetchone()
    if not row or row[1] < time.time():
        return "Not found or expired", 404
    return redirect(row[0], code=302)


@app.route("/api/qr", methods=["POST"])
def qr():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if not text:
        return err("text required")
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/hash", methods=["POST"])
def hash_pw():
    data = request.get_json(silent=True) or {}
    pw = data.get("text")
    if not pw:
        return err("text required")
    h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    return jsonify({"hash": h})


@app.route("/api/verify-hash", methods=["POST"])
def verify_pw():
    data = request.get_json(silent=True) or {}
    pw, h = data.get("text"), data.get("hash")
    if not pw or not h:
        return err("text and hash required")
    try:
        ok = bcrypt.checkpw(pw.encode(), h.encode())
    except ValueError:
        return err("invalid hash")
    return jsonify({"match": ok})


@app.route("/api/uuid", methods=["POST"])
def gen_uuid():
    data = request.get_json(silent=True) or {}
    n = min(int(data.get("count", 1)), 100)
    return jsonify({"uuids": [str(uuid.uuid4()) for _ in range(n)]})


@app.route("/api/random", methods=["POST"])
def gen_random():
    data = request.get_json(silent=True) or {}
    length = min(int(data.get("length", 32)), 512)
    charset = data.get("charset", "alnum")
    pools = {
        "alnum": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "hex": "0123456789abcdef",
        "base64": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
    }
    pool = pools.get(charset, pools["alnum"])
    value = "".join(secrets.choice(pool) for _ in range(length))
    return jsonify({"value": value})


@app.route("/api/base64", methods=["POST"])
def b64():
    data = request.get_json(silent=True) or {}
    op, text = data.get("op"), data.get("text")
    if op not in ("encode", "decode") or text is None:
        return err("op (encode|decode) and text required")
    try:
        if op == "encode":
            out = base64.b64encode(text.encode()).decode()
        else:
            out = base64.b64decode(text).decode()
    except Exception as e:
        return err(f"base64 error: {e}")
    return jsonify({"result": out})


def _diff(a, b, path=""):
    out = []
    if type(a) != type(b):
        out.append({"path": path, "from": a, "to": b})
    elif isinstance(a, dict):
        for k in a.keys() | b.keys():
            p = f"{path}.{k}" if path else k
            if k not in a:
                out.append({"path": p, "added": b[k]})
            elif k not in b:
                out.append({"path": p, "removed": a[k]})
            else:
                out.extend(_diff(a[k], b[k], p))
    elif isinstance(a, list):
        for i in range(max(len(a), len(b))):
            p = f"{path}[{i}]"
            if i >= len(a):
                out.append({"path": p, "added": b[i]})
            elif i >= len(b):
                out.append({"path": p, "removed": a[i]})
            else:
                out.extend(_diff(a[i], b[i], p))
    elif a != b:
        out.append({"path": path, "from": a, "to": b})
    return out


@app.route("/api/json-diff", methods=["POST"])
def json_diff():
    data = request.get_json(silent=True) or {}
    a, b = data.get("a"), data.get("b")
    if a is None or b is None:
        return err("a and b required")
    return jsonify({"diff": _diff(a, b)})


@app.route("/api/regex-test", methods=["POST"])
def regex_test():
    data = request.get_json(silent=True) or {}
    pattern, text = data.get("pattern"), data.get("text")
    if pattern is None or text is None:
        return err("pattern and text required")
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return err(f"invalid regex: {e}")
    matches = [
        {"match": m.group(0), "groups": list(m.groups()), "span": m.span()}
        for m in rx.finditer(text)
    ]
    return jsonify({"matches": matches, "count": len(matches)})


@app.route("/api/cron-parse", methods=["POST"])
def cron_parse():
    data = request.get_json(silent=True) or {}
    expr = data.get("expr")
    n = min(int(data.get("count", 5)), 50)
    if not expr:
        return err("expr required")
    try:
        it = croniter(expr, datetime.now())
        runs = [it.get_next(datetime).isoformat() for _ in range(n)]
    except Exception as e:
        return err(f"invalid cron: {e}")
    return jsonify({"next": runs})


@app.route("/api/vat", methods=["POST"])
def vat():
    data = request.get_json(silent=True) or {}
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return err("amount required (number)")
    rate = float(data.get("rate", 24))
    vat_val = round(amount * rate / 100, 2)
    return jsonify({"amount": amount, "rate": rate, "vat": vat_val, "total": round(amount + vat_val, 2)})


@app.route("/api/card-validate", methods=["POST"])
def card_validate():
    data = request.get_json(silent=True) or {}
    num = re.sub(r"\D", "", str(data.get("number", "")))
    if not num:
        return err("number required")
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    luhn = total % 10 == 0
    card_type = (
        "visa" if num.startswith("4")
        else "mastercard" if num[:2] in ("51", "52", "53", "54", "55")
        else "amex" if num[:2] in ("34", "37")
        else "discover" if num.startswith("6011")
        else "unknown"
    )
    return jsonify({"valid": luhn, "type": card_type, "luhn": luhn})


@app.route("/api/password-strength", methods=["POST"])
def pw_strength():
    data = request.get_json(silent=True) or {}
    pw = data.get("password", "")
    score = 0
    if len(pw) >= 8:
        score += 1
    if len(pw) >= 12:
        score += 1
    if re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw):
        score += 1
    if re.search(r"\d", pw):
        score += 1
    if re.search(r"[^A-Za-z0-9]", pw):
        score += 1
    labels = ["very weak", "weak", "fair", "good", "strong", "very strong"]
    return jsonify({"score": score, "label": labels[min(score, 5)]})


@app.route("/api/totp", methods=["POST"])
def totp_gen():
    data = request.get_json(silent=True) or {}
    secret = data.get("secret")
    if not secret:
        return err("secret required")
    try:
        code = pyotp.TOTP(secret).now()
    except Exception as e:
        return err(f"invalid secret: {e}")
    return jsonify({"code": code, "period": 30})


@app.route("/api/totp-verify", methods=["POST"])
def totp_verify():
    data = request.get_json(silent=True) or {}
    secret, code = data.get("secret"), data.get("code")
    if not secret or not code:
        return err("secret and code required")
    try:
        ok = pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception as e:
        return err(f"invalid secret: {e}")
    return jsonify({"valid": ok})


@app.route("/api/jwt/decode", methods=["POST"])
def jwt_decode():
    data = request.get_json(silent=True) or {}
    token = data.get("token", "")
    parts = token.split(".")
    if len(parts) != 3:
        return err("invalid JWT")

    def _dec(seg):
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))

    try:
        return jsonify({"header": _dec(parts[0]), "payload": _dec(parts[1])})
    except Exception as e:
        return err(f"decode error: {e}")


@app.route("/api/duration", methods=["POST"])
def duration():
    data = request.get_json(silent=True) or {}
    try:
        start = int(data.get("start"))
        end = int(data.get("end"))
    except (TypeError, ValueError):
        return err("start and end required (unix timestamps)")
    secs = end - start
    h, rem = divmod(abs(secs), 3600)
    m, s = divmod(rem, 60)
    human = f"{h}h {m}m {s}s"
    return jsonify({"seconds": secs, "human": human})


@app.route("/api/timezone", methods=["POST"])
def timezone_lookup():
    data = request.get_json(silent=True) or {}
    tz_name = data.get("tz", "Europe/Athens")
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception as e:
        return err(f"invalid timezone: {e}")
    now = datetime.now(dt_timezone.utc)
    local = now.astimezone(tz)
    return jsonify({
        "timezone": tz_name,
        "utc_now": now.isoformat(),
        "local_now": local.isoformat(),
        "offset": local.utcoffset().total_seconds() / 3600,
    })


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ==================================================================
#  MCP GATEWAY
# ==================================================================

def get_tenant():
    key = request.headers.get("X-API-Key", "")
    if not key:
        return None
    return VALID_KEY_HASHES.get(hashlib.sha256(key.encode()).hexdigest())


def get_trust_grade(server_slug):
    try:
        r = requests.get(f"{MCP_TRUST_API}/servers/{server_slug}", timeout=3)
        if r.status_code == 200:
            data = r.json()
            return data.get("grade") or data.get("danger_grade") or "UNKNOWN"
    except Exception:
        pass
    return "UNKNOWN"


def estimate_cost(tool_name, arguments):
    arg_bytes = len(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))
    est_tokens = (arg_bytes * TOKENS_PER_ARG_BYTE) + len(tool_name) + 50
    return round((est_tokens / 1000) * COST_PER_1K_TOKENS, 4)


def get_or_create_session(session_id, tenant):
    with sqlite3.connect(GATEWAY_DB) as c:
        row = c.execute(
            "SELECT total_spent, cap FROM sessions WHERE session_id=?",
            (session_id,)
        ).fetchone()
        if row:
            return row[0], row[1]
        c.execute(
            "INSERT INTO sessions VALUES (?, ?, 0, ?, ?)",
            (session_id, tenant, DEFAULT_SESSION_CAP, int(time.time()))
        )
        return 0.0, DEFAULT_SESSION_CAP


def update_session_spend(session_id, amount):
    with sqlite3.connect(GATEWAY_DB) as c:
        c.execute(
            "UPDATE sessions SET total_spent = total_spent + ? WHERE session_id=?",
            (amount, session_id)
        )


def log_audit(tenant, session_id, server_slug, tool_name, arguments,
              est_cost, trust, decision, reason):
    with sqlite3.connect(GATEWAY_DB) as c:
        c.execute("""
            INSERT INTO audit (ts, tenant, session_id, server_slug, tool_name,
                               arguments, estimated_cost, trust_grade, decision, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            int(time.time()), tenant, session_id, server_slug, tool_name,
            json.dumps(arguments)[:500], est_cost, trust, decision, reason
        ))


@app.route("/v1/proxy", methods=["POST"])
@limiter.limit("100 per hour")
def proxy():
    tenant = get_tenant()
    if not tenant:
        return jsonify({
            "error": "unauthorized",
            "reason": "Missing or invalid X-API-Key header",
        }), 401

    data = request.get_json(silent=True) or {}
    server_slug = data.get("server_slug")
    tool_name = data.get("tool_name")
    arguments = data.get("arguments", {})
    session_id = data.get("session_id", "default")

    if not server_slug or not tool_name:
        return jsonify({"error": "server_slug and tool_name required"}), 400

    trust = get_trust_grade(server_slug)
    if trust != "UNKNOWN" and trust > TRUST_THRESHOLD:
        log_audit(tenant, session_id, server_slug, tool_name, arguments,
                  0, trust, "BLOCKED", f"trust grade {trust} below threshold")
        return jsonify({
            "error": "blocked_by_trust",
            "reason": f"Server trust grade '{trust}' is below threshold '{TRUST_THRESHOLD}'",
            "trust_grade": trust,
        }), 403

    est_cost = estimate_cost(tool_name, arguments)

    spent, cap = get_or_create_session(session_id, tenant)
    if spent + est_cost > cap:
        log_audit(tenant, session_id, server_slug, tool_name, arguments,
                  est_cost, trust, "BLOCKED", "session cap exceeded")
        return jsonify({
            "error": "budget_exceeded",
            "reason": f"Estimated cost ${est_cost} would exceed remaining budget ${round(cap - spent, 4)}",
            "estimated_cost": est_cost,
            "spent": round(spent, 4),
            "cap": cap,
        }), 402

    server_url = MCP_SERVERS.get(server_slug)
    if not server_url:
        log_audit(tenant, session_id, server_slug, tool_name, arguments,
                  est_cost, trust, "BLOCKED", "server_not_found")
        return jsonify({
            "error": "server_not_found",
            "reason": f"No backend configured for '{server_slug}'",
            "configured": list(MCP_SERVERS.keys()),
        }), 404

    try:
        upstream = requests.post(
            f"{server_url}/tools/{tool_name}",
            json=arguments,
            timeout=30,
        )
    except requests.RequestException as e:
        log_audit(tenant, session_id, server_slug, tool_name, arguments,
                  est_cost, trust, "ERROR", str(e))
        return jsonify({"error": "upstream_error", "reason": str(e)}), 502

    if upstream.ok:
        update_session_spend(session_id, est_cost)
        log_audit(tenant, session_id, server_slug, tool_name, arguments,
                  est_cost, trust, "ALLOWED", "")
    else:
        log_audit(tenant, session_id, server_slug, tool_name, arguments,
                  est_cost, trust, "UPSTREAM_ERROR", f"status {upstream.status_code}")

    try:
        result = upstream.json()
    except ValueError:
        result = upstream.text

    return jsonify({
        "allowed": True,
        "estimated_cost": est_cost,
        "spent": round(spent + (est_cost if upstream.ok else 0), 4),
        "cap": cap,
        "remaining": round(cap - (spent + (est_cost if upstream.ok else 0)), 4),
        "trust_grade": trust,
        "result": result,
        "upstream_status": upstream.status_code,
    }), 200 if upstream.ok else 502


@app.route("/v1/policy", methods=["POST"])
@limiter.limit("30 per minute")
def set_policy():
    tenant = get_tenant()
    if not tenant:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "default")
    cap = float(data.get("cap", DEFAULT_SESSION_CAP))
    with sqlite3.connect(GATEWAY_DB) as c:
        c.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?, COALESCE((SELECT total_spent FROM sessions WHERE session_id=?), 0), ?, ?)",
            (session_id, tenant, session_id, cap, int(time.time()))
        )
    return jsonify({"session_id": session_id, "cap": cap, "tenant": tenant})


@app.route("/v1/audit", methods=["GET"])
def get_audit():
    tenant = get_tenant()
    if not tenant:
        return jsonify({"error": "unauthorized"}), 401
    session_id = request.args.get("session_id")
    limit = min(int(request.args.get("limit", 50)), 500)
    with sqlite3.connect(GATEWAY_DB) as c:
        if session_id:
            rows = c.execute(
                "SELECT * FROM audit WHERE tenant=? AND session_id=? ORDER BY id DESC LIMIT ?",
                (tenant, session_id, limit)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM audit WHERE tenant=? ORDER BY id DESC LIMIT ?",
                (tenant, limit)
            ).fetchall()
    cols = ["id", "ts", "tenant", "session_id", "server_slug", "tool_name",
            "arguments", "estimated_cost", "trust_grade", "decision", "reason"]
    return jsonify([dict(zip(cols, r)) for r in rows])


@app.route("/v1/health")
def gateway_health():
    return jsonify({"status": "ok"})


# ==================================================================
#  TESTER PAGE
# ==================================================================

@app.route("/", methods=["GET"])
def index():
    return TESTER_HTML


TESTER_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>MCP Local Gateway</title>
<style>
body{font-family:system-ui;max-width:900px;margin:2rem auto;padding:0 1rem;line-height:1.5}
section{border:1px solid #ccc;border-radius:8px;padding:1rem;margin:1rem 0}
textarea,input{width:100%;font-family:monospace;padding:.4rem;margin:.2rem 0;box-sizing:border-box}
button{padding:.5rem 1rem;cursor:pointer;margin:.2rem}
pre{background:#f6f6f6;padding:.8rem;overflow:auto;max-height:400px;border-radius:6px}
small{color:#666}
</style></head><body>
<h1>MCP Local Gateway</h1>
<p>API tester. Use <code>X-API-Key</code> for authenticated endpoints.</p>

<section>
  <h3>API Key</h3>
  <input id="api-key" value="" placeholder="X-API-Key">
</section>

<section>
  <h3>Proxy Call</h3>
  <textarea id="payload" rows="6">{
  "server_slug": "weather",
  "tool_name": "get_forecast",
  "arguments": {"city": "Athens", "days": 3},
  "session_id": "test-session-1"
}</textarea>
  <button onclick="callProxy()">Call /v1/proxy</button>
  <pre id="proxy-result">—</pre>
</section>

<section>
  <h3>Set Policy (cap)</h3>
  <textarea id="policy-payload" rows="3">{"session_id": "test-session-1", "cap": 0.01}</textarea>
  <button onclick="callPolicy()">Set</button>
  <pre id="policy-result">—</pre>
</section>

<section>
  <h3>Audit Log</h3>
  <button onclick="callAudit()">Fetch audit</button>
  <pre id="audit-result">—</pre>
</section>

<script>
function headers() {
  return {
    'Content-Type': 'application/json',
    'X-API-Key': document.getElementById('api-key').value
  };
}
async function callProxy() {
  const pre = document.getElementById('proxy-result');
  pre.textContent = '…';
  try {
    const res = await fetch('/v1/proxy', {
      method: 'POST',
      headers: headers(),
      body: document.getElementById('payload').value
    });
    const text = await res.text();
    try { pre.textContent = '[' + res.status + '] ' + JSON.stringify(JSON.parse(text), null, 2); }
    catch { pre.textContent = '[' + res.status + '] ' + text; }
  } catch (e) { pre.textContent = 'Error: ' + e.message; }
}
async function callPolicy() {
  const pre = document.getElementById('policy-result');
  pre.textContent = '…';
  try {
    const res = await fetch('/v1/policy', {
      method: 'POST',
      headers: headers(),
      body: document.getElementById('policy-payload').value
    });
    const text = await res.text();
    try { pre.textContent = '[' + res.status + '] ' + JSON.stringify(JSON.parse(text), null, 2); }
    catch { pre.textContent = '[' + res.status + '] ' + text; }
  } catch (e) { pre.textContent = 'Error: ' + e.message; }
}
async function callAudit() {
  const pre = document.getElementById('audit-result');
  pre.textContent = '…';
  try {
    const res = await fetch('/v1/audit?session_id=test-session-1&limit=20', {
      headers: headers()
    });
    const text = await res.text();
    try { pre.textContent = '[' + res.status + '] ' + JSON.stringify(JSON.parse(text), null, 2); }
    catch { pre.textContent = '[' + res.status + '] ' + text; }
  } catch (e) { pre.textContent = 'Error: ' + e.message; }
}
</script></body></html>"""


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5002, debug=False)
