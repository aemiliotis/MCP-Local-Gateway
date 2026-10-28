# MCP Local Gateway

A **self-hosted governance layer** for [MCP](https://modelcontextprotocol.io/) servers.
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
