#!/bin/bash
set -euo pipefail

echo "==> Creating virtual environment"
python3 -m venv venv
source venv/bin/activate

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Copying .env.example to .env (edit it before running)"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "    Created .env — edit it and set API_KEYS_JSON / MCP_SERVERS_JSON"
fi

echo "==> Done. Next steps:"
echo "    1. Edit .env"
echo "    2. python mock_mcp.py &   # optional mock backend"
echo "    3. python app.py"
