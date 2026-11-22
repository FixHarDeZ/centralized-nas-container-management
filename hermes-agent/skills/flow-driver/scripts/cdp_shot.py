#!/usr/bin/env python3
"""Capture a rectangular clip of the open Flow project tab straight to a JPEG.

Why this exists: Page.captureScreenshot returns base64 INSIDE the CDP reply, so reading it
through a tool puts tens of thousands of tokens of context in the way before the pixels can
be saved - and the reply cannot be written to disk from the tool. This runs the capture on a
tiny websocket session and writes only the file, printing just the byte count.

Usage:
  uv run --with websocket-client python -I cdp_shot.py <out.jpg> <x> <y> <w> <h> [scale]

Coordinates are CSS pixels of the viewport; scale multiplies the output (4 -> a 50px chip
becomes 200px). Chrome must be on 127.0.0.1:9222 with a flow.google.com/project/ tab open.
Then: vision_analyze <out.jpg>.
"""
import base64
import json
import sys
import urllib.request

import websocket  # provided by `uv run --with websocket-client`

CDP = "http://127.0.0.1:9222"


def main():
    if len(sys.argv) < 6:
        raise SystemExit("usage: cdp_shot.py <out.jpg> <x> <y> <w> <h> [scale]")
    out = sys.argv[1]
    x, y, w, h = (float(v) for v in sys.argv[2:6])
    scale = float(sys.argv[6]) if len(sys.argv) > 6 else 1.0

    targets = json.load(urllib.request.urlopen(CDP + "/json/list"))
    ws_url = next(
        (t["webSocketDebuggerUrl"] for t in targets
         if t.get("type") == "page" and "flow.google.com/project/" in t.get("url", "")),
        None)
    if not ws_url:
        raise SystemExit("no Flow project tab on :9222")

    ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
    state = {"n": 0}

    def call(method, **params):
        state["n"] += 1
        ws.send(json.dumps({"id": state["n"], "method": method, "params": params}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == state["n"]:
                return msg.get("result") or msg.get("error") or {}

    res = call("Page.captureScreenshot", format="jpeg", quality=85,
               clip={"x": x, "y": y, "width": w, "height": h, "scale": scale})
    data = res.get("data") if isinstance(res, dict) else None
    if not data:
        raise SystemExit("capture failed: %s" % json.dumps(res)[:300])
    raw = base64.b64decode(data)
    with open(out, "wb") as fh:
        fh.write(raw)
    print("wrote %s (%d bytes)" % (out, len(raw)))


if __name__ == "__main__":
    main()
