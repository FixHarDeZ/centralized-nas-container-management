#!/usr/bin/env python3
"""File side of the desk, for the drawer in the page.

    PUT    /upload/in/<name>    write a source file into <work>/in
    DELETE /upload/<dir>/<name> remove one file from <work>/in or <work>/out
    DELETE /upload/<dir>/       remove every file in that folder

Runs inside the desk container (which already owns /work) next to ttyd on
port 7682. The nginx sidecar is the only thing that can reach it, and it sits
behind basic auth there; nginx also caps the body size. This process only
enforces which paths are legal.

Deletes are permanent. DSM's recycle bin is implemented by the file services,
not the filesystem, so os.unlink from a container skips it entirely.

Set WORK_DIR to run it anywhere (used to exercise it outside the container).
"""
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

WORK_DIR = os.environ.get("WORK_DIR", "/work")
PORT = int(os.environ.get("UPLOAD_PORT", "7682"))

# The two folders the page knows about. Anything else is a 404: the share
# root holds #recycle and @eaDir, which must never be reachable from here.
DIRS = {"in": os.path.join(WORK_DIR, "in"), "out": os.path.join(WORK_DIR, "out")}

SAFE = re.compile(r"^[^/\\\x00]{1,200}$")


def safe_name(segment: str):
    """One path segment → a flat filename, or None.

    The check runs *after* unquoting on a segment that was split off the raw
    path, so an encoded separator (%2F, %5C) is rejected here rather than
    silently becoming a directory step.
    """
    name = unquote(segment).strip()
    if not SAFE.match(name) or name in (".", "..") or name.startswith("."):
        return None
    return name


class Handler(BaseHTTPRequestHandler):
    server_version = "claude-desk-files/2"

    def _reply(self, code: int, body: str = ""):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _route(self):
        """('in'|'out', name or None) — None name means "the whole folder"."""
        raw = self.path.split("?", 1)[0]
        parts = raw.split("/")
        # ['', 'upload', <dir>, <name or ''>] and nothing deeper
        if len(parts) != 4 or parts[0] != "" or parts[1] != "upload":
            self._reply(404, "not here")
            return None, None
        folder = DIRS.get(unquote(parts[2]))
        if folder is None:
            self._reply(404, "no such folder")
            return None, None
        if parts[3] == "":
            return folder, None
        name = safe_name(parts[3])
        if not name:
            self._reply(400, "bad name")
            return None, None
        return folder, name

    def do_PUT(self):
        folder, name = self._route()
        if folder is None:
            return
        if name is None:
            self._reply(405, "name required")
            return
        if folder != DIRS["in"]:
            # out/ is Claude's output; uploading over it would only confuse.
            self._reply(403, "uploads go to in/")
            return
        path = os.path.join(folder, name)
        tmp = path + ".part"
        length = int(self.headers.get("Content-Length") or 0)
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
        folder, name = self._route()
        if folder is None:
            return
        if name is None:
            self._reply(200, str(self._clear(folder)))
            return
        try:
            os.unlink(os.path.join(folder, name))
        except FileNotFoundError:
            self._reply(404, "no such file")
            return
        except OSError as e:
            self._reply(500, str(e))
            return
        self._reply(204)

    @staticmethod
    def _clear(folder: str) -> int:
        """Unlink every plain file directly in folder. Returns how many.

        Subdirectories are left alone — that keeps Synology's @eaDir (and
        anything Claude organised into a folder) out of it. A .part file
        belonging to an upload still in flight is removed like any other,
        and that upload then fails on its rename; clearing mid-upload is
        assumed to be what was meant.
        """
        removed = 0
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return 0
        for entry in entries:
            if entry.name.startswith(".") or not entry.is_file(follow_symlinks=False):
                continue
            try:
                os.unlink(entry.path)
                removed += 1
            except OSError:
                pass
        return removed

    def log_message(self, fmt, *args):  # one line per request, to the container log
        sys.stderr.write("[upload] %s %s\n" % (self.command, fmt % args))


if __name__ == "__main__":
    for d in DIRS.values():
        os.makedirs(d, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
