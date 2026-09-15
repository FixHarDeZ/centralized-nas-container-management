#!/usr/bin/env python3
"""Upload side of the desk: PUT /upload/<name> writes into /work/in.

Runs inside the desk container (which already owns /work) next to ttyd, on
127.0.0.1-only-in-spirit port 7682 — the nginx sidecar is the only thing
that can reach it, and it sits behind basic auth there. nginx enforces the
size limit; this only enforces the path.

Deliberately stdlib-only and tiny: one folder, flat names, no directories.
"""
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

IN_DIR = "/work/in"
PORT = int(os.environ.get("UPLOAD_PORT", "7682"))
SAFE = re.compile(r"^[^/\\\x00]{1,200}$")


def safe_name(raw: str):
    name = unquote(raw).strip()
    if not SAFE.match(name) or name in (".", "..") or name.startswith("."):
        return None
    return name


class Handler(BaseHTTPRequestHandler):
    server_version = "claude-desk-upload/1"

    def _reply(self, code: int, body: str = ""):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _target(self):
        if not self.path.startswith("/upload/"):
            self._reply(404, "not here")
            return None
        name = safe_name(self.path[len("/upload/"):])
        if not name:
            self._reply(400, "bad name")
            return None
        return os.path.join(IN_DIR, name)

    def do_PUT(self):
        path = self._target()
        if not path:
            return
        length = int(self.headers.get("Content-Length") or 0)
        tmp = path + ".part"
        try:
            with open(tmp, "wb") as f:
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            os.replace(tmp, path)   # atomic: never a half file under its real name
        except OSError as e:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            self._reply(500, str(e))
            return
        self._reply(201, "ok")

    def do_DELETE(self):
        path = self._target()
        if not path:
            return
        try:
            os.unlink(path)
        except FileNotFoundError:
            self._reply(404, "no such file")
            return
        except OSError as e:
            self._reply(500, str(e))
            return
        self._reply(204)

    def log_message(self, fmt, *args):  # one line per request, to the container log
        sys.stderr.write("[upload] %s %s\n" % (self.command, fmt % args))


if __name__ == "__main__":
    os.makedirs(IN_DIR, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
