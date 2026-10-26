"""
Minimal mock MCP server for local testing.

Run: python mock_mcp.py
Then call the gateway at /v1/proxy with server_slug="weather".
"""

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.route("/tools/<tool_name>", methods=["POST"])
def tool(tool_name):
    args = request.json or {}
    city = args.get("city", "unknown")
    return jsonify({
        "tool": tool_name,
        "args": args,
        "result": f"sunny with 25C in {city}",
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9001)
