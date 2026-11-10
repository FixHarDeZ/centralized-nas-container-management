#!/usr/bin/env python3
"""Upload one or more reference files into a Google Flow project via the picker.

Why one script: Page.setInterceptFileChooserDialog and the transient <input type=file>
only survive inside ONE CDP websocket connection. Separate stateless CDP calls each open
a new connection, so the interception flag is lost and the input is not found.

Run (uv supplies websocket-client; -I ignores cwd modules):
  uv run --with websocket-client python -I flow_upload_ref.py <abs_file> [<abs_file> ...]

Prerequisite: Chrome is up on 127.0.0.1:9222 with a Flow project tab open, and the
Ingredients picker is already open on the 'Uploads' category (the script clicks
'Upload media' itself but does not open the picker or switch category).

Verdict: the filenames appearing in the printed overlay text. The DOM.setFileInputFiles
reply ({}) is not proof.
"""
import json
import sys
import time
import urllib.request

import websocket  # provided by `uv run --with websocket-client`

CDP = "http://127.0.0.1:9222"


def page_ws_url():
    targets = json.load(urllib.request.urlopen(CDP + "/json/list"))
    for t in targets:
        if t.get("type") == "page" and "flow.google.com/project/" in t.get("url", ""):
            return t["webSocketDebuggerUrl"]
    raise SystemExit("no Flow project tab on :9222")


def main(files):
    ws = websocket.create_connection(page_ws_url(), timeout=30, suppress_origin=True)
    counter = [0]

    def call(method, **params):
        counter[0] += 1
        mid = counter[0]
        ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid:
                return msg.get("result", {}) if "error" not in msg else {"error": msg["error"]}

    def ev(expr):
        return call("Runtime.evaluate", expression=expr, returnByValue=True).get("result", {}).get("value")

    call("Page.enable")
    call("DOM.enable")
    call("Page.setInterceptFileChooserDialog", enabled=True)
    try:
        btn = ev("""(() => { const el=[...document.querySelectorAll('.cdk-overlay-container *')]
            .find(e=>e.children.length===0 && e.innerText && e.innerText.trim()==='Upload media');
            if(!el) return null; const r=el.getBoundingClientRect();
            return {x:r.x+r.width/2, y:r.y+r.height/2}; })()""")
        if not btn:
            raise SystemExit("Upload media not found: open the picker and select the Uploads category first")
        for t in ("mousePressed", "mouseReleased"):
            call("Input.dispatchMouseEvent", type=t, x=btn["x"], y=btn["y"], button="left", clickCount=1)
        nid = 0
        for _ in range(20):
            time.sleep(0.5)
            root = call("DOM.getDocument", depth=-1, pierce=True).get("root", {}).get("nodeId")
            if root:
                nid = call("DOM.querySelector", nodeId=root, selector="input[type=file]").get("nodeId", 0)
            if nid:
                break
        if not nid:
            raise SystemExit("no input[type=file] appeared after clicking Upload media")
        print("setFileInputFiles:", call("DOM.setFileInputFiles", files=files, nodeId=nid))
    finally:
        call("Page.setInterceptFileChooserDialog", enabled=False)
    time.sleep(8)
    print("overlay after upload:", ev("(() => { const o=document.querySelector('.cdk-overlay-container'); return o ? o.innerText.slice(0,800) : ''; })()"))
    ws.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: flow_upload_ref.py <abs_file> [...]")
    main([p for p in sys.argv[1:]])
