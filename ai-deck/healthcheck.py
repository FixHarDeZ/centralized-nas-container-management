#!/usr/bin/env python3
"""Container healthcheck: every process the page talks to answers.

ttyd is PID 1, so a running container only proves the first desk's terminal.
upload.py, chat.py and the other desks' ttyd live in respawn loops and can be
down (or crash-looping) while Docker still says "running" — which is all
Uptime Kuma's docker monitor saw. A failing check turns the container
unhealthy, and Kuma's docker monitor reports that as DOWN.
"""
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 3


def targets(environ=os.environ):
    """(name, url) for each process, from the same env the entrypoint reads."""
    out = [
        ("upload.py", "http://127.0.0.1:%s/api/health" % environ.get("UPLOAD_PORT", "7682")),
        ("chat.py", "http://127.0.0.1:%s/chat/health" % environ.get("CHAT_PORT", "7683")),
    ]
    ports = []
    for entry in environ.get("DESK_USERS", "").split(","):
        port = entry.rpartition(":")[2].strip()
        if port.isdigit() and port not in ports:
            ports.append(port)
    for port in ports or ["7681"]:
        out.append(("ttyd:" + port, "http://127.0.0.1:%s/" % port))
    return out


def failures(checks, opener=urllib.request.urlopen):
    bad = []
    for name, url in checks:
        try:
            with opener(url, timeout=TIMEOUT) as response:
                if response.status >= 400:
                    bad.append("%s HTTP %d" % (name, response.status))
        except urllib.error.HTTPError as error:
            bad.append("%s HTTP %d" % (name, error.code))
        except (OSError, ValueError) as error:
            bad.append("%s %s" % (name, getattr(error, "reason", error)))
    return bad


def main():
    bad = failures(targets())
    if bad:
        print("unhealthy: " + "; ".join(bad))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
