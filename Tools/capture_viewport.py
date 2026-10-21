"""Save a PNG of the editor's level viewport, via the UE MCP server.

Usage:
    python Tools/capture_viewport.py [out.png]

Default output: Saved/Screenshots/viewport.png. Calling CaptureViewport through
an MCP client returns the PNG as base64 text, which is why this script exists.
"""
import base64
import http.client
import json
import sys
from pathlib import Path

session = None


def post(body):
    global session
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    # urllib gets an empty body from this server; http.client works.
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=60)
    conn.request("POST", "/mcp", json.dumps(body), headers)
    resp = conn.getresponse()
    session = session or resp.getheader("Mcp-Session-Id")
    return resp.read().decode()


def call(tool, arguments):
    text = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "call_tool", "arguments": {
        "toolset_name": "EditorToolset.EditorAppToolset", "tool_name": tool, "arguments": arguments}}})
    # tools/call answers as SSE: "event: message\ndata: {...}"
    result = json.loads(next(line[6:] for line in text.splitlines() if line.startswith("data: ")))["result"]
    if result.get("isError"):
        sys.exit(result["content"][0]["text"])
    return json.loads(result["content"][0]["text"])["returnValue"]


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "Saved/Screenshots/viewport.png"
    post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "capture_viewport", "version": "1"}}})
    post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    camera = call("GetCameraTransform", {})
    # The server wants every argument; zero spacing/distance turns the overlays off.
    no_overlay = {"gridSpacing": 0, "gridExtent": 0, "gridHeight": 0, "maxLabelDistance": 0, "classFilter": None, "maxLabels": 0}
    image = call("CaptureViewport", {"captureTransform": camera, "annotations": no_overlay, "bShowUI": False})["image"]["data"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(image))
    print(out)


if __name__ == "__main__":
    main()
