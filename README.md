# MCP-Local-Gateway
MCP Local Gateway — ένα self-hosted gateway για MCP servers, με authentication, rate limiting, cost caps, trust checks και audit logMCP Local Gateway — ένα self-hosted gateway για MCP servers, με authentication, rate limiting, cost caps, trust checks και audit log

# MCP Local Gateway

A **self-hosted governance layer** for [MCP](https://logictech.neocities.org/logicteck1) servers.
It sits between your AI agent and any MCP server and adds:

- **API key authentication** (`X-API-Key`)
- **Redis-backed rate limiting** (shared across Gunicorn workers)
- **Pre-run cost estimation** (tokens → dollars)
- **Hard budget caps** per session
- **Trust scoring** (A–F) via an external trust API
- **Full audit log** (per tenant, per session)
- **18 built-in micro-APIs** (QR, hashing, UUID, VAT, TOTP, JWT decode, …)

No UI required — everything is JSON over HTTP.

## Architecture

Developer's code
│
▼
Tailscale Funnel (HTTPS) ── or any reverse proxy
│
▼
Nginx (127.0.0.1:8080)
│
▼
Unix socket → Gunicorn (3 workers) → Flask app.py
│
├── /v1/proxy → MCP gateway
├── /v1/policy → set budget cap
├── /v1/audit → audit log
├── /api/* → micro-APIs
└── / → tester page
│
├── Redis (rate limiting)
├── gateway.db (sessions + audit)
└── api.db (short links)


## Quick start

```bash
git clone <your-repo-url>
cd mcp-local-gateway

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set API_KEYS_JSON, MCP_SERVERS_JSON

# start a mock MCP server for testing
python mock_mcp.py &

# start the gateway
python app.py

Then open http://127.0.0.1:5002/ for the tester page.

Calling the gateway
curl -X POST http://127.0.0.1:5002/v1/proxy \
  -H "X-API-Key: test-key-123" \
  -H "Content-Type: application/json" \
  -d '{
    "server_slug": "weather",
    "tool_name": "get_forecast",
    "arguments": {"city": "Athens"},
    "session_id": "user-42-task-7"
  }'


Response:
{
  "allowed": true,
  "estimated_cost": 0.0001,
  "spent": 0.0001,
  "cap": 5.0,
  "remaining": 4.9999,
  "trust_grade": "UNKNOWN",
  "result": {"tool": "get_forecast", "args": {"city": "Athens"}, "result": "sunny with 25C in Athens"},
  "upstream_status": 200
}

Endpoint	Method	Auth	Purpose
/v1/proxy	POST	✅	Forward a tool call to an MCP server
/v1/policy	POST	✅	Set the budget cap for a session
/v1/audit	GET	✅	Fetch audit log entries
/v1/health	GET	❌	Liveness check
/api/*	POST	❌	Micro-APIs (see tester page)
/	GET	❌	HTML tester


Environment variables
See .env.example. All variables are optional — sensible defaults are used.

Key ones:

API_KEYS_JSON — map of sha256(raw_key) → tenant name

MCP_SERVERS_JSON — map of slug → base URL

REDIS_URL — defaults to redis://localhost:6379/0; falls back to in-memory if unreachable

TRUST_THRESHOLD — minimum allowed grade (A–F), default C

Generate a key hash:
python -c "import hashlib; print(hashlib.sha256(b'your-raw-key').hexdigest())"

Production deployment
See systemd/ and nginx/ for ready-to-use service and reverse-proxy configs.

Steps
1. Gunicorn + systemd
sudo cp systemd/mcp-local-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-local-gateway

2. Nginx reverse proxy
sudo cp nginx/mcp-local-gateway.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/mcp-local-gateway.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

3. Expose publicly (optional)
Tailscale Funnel: tailscale funnel 8080
Or Cloudflare Tunnel, ngrok, etc.

4. Backups
chmod +x scripts/backup_gateway.sh
crontab -e
# add: 0 3 * * * /path/to/mcp-local-gateway/scripts/backup_gateway.sh

5. Security notes
Never enable Flask debug=True in production.

Always use HTTPS (Tailscale Funnel, Cloudflare, or Let's Encrypt).

Rotate API keys regularly; store only their SHA-256 hashes.

The gateway is not a substitute for securing each MCP server — it is an additional governance layer.

Rate limits and budget caps are enforced server-side; don't rely on the client.
