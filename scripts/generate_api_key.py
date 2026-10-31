#!/usr/bin/env python3
"""
Generate a raw API key and its SHA-256 hash for MCP Local Gateway.

Usage:
    python scripts/generate_api_key.py
"""

import hashlib
import secrets
import sys


def main():
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()

    print("=" * 60)
    print("MCP Local Gateway - API Key Generator")
    print("=" * 60)
    print()
    print("RAW KEY (give this to the caller):")
    print(f"  {raw}")
    print()
    print("SHA-256 HASH (put this in .env under API_KEYS_JSON):")
    print(f'  "{hashed}": "tenant-1"')
    print()
    print("Example .env line:")
    print(f'  API_KEYS_JSON={{"{hashed}":"tenant-1"}}')
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
