"""One heavy job at a time inside hermes-gateway (whisper, ffmpeg builds, post).

Why: the container is cgroup-fenced at 4 GB. Two heavy scripts at once, or one that grows too far, are
SIGKILLed with no traceback (2026-11-11: 6 kills, 2026-11-12: 2). The rule "heavy work one at a time"
lived only in the skill text.

    import heavylock; heavylock.acquire("post_presenter")

- Holds an flock on HEAVY_LOCK for the life of the process. A child started by the holder inherits
  HEAVY_LOCK_HELD and does not lock again (product_build -> its whisper subprocess).
- Busy: polls for HEAVY_WAIT_S (default 120 s, under the 180 s terminal timeout), then exits 75 and
  names the holder. Rerun the same command later; do not start a different heavy job meanwhile.
- Every run appends to HEAVY_LOG: a "start" row, and an "end" row with seconds and peak RSS (self +
  children). A "start" with no "end" = that run was killed (OOM or timeout).
- The lock directory missing (workstation, tests) = no lock, no log.
"""
import atexit
import contextlib
import fcntl
import json
import os
import resource
import sys
import time

LOCK = os.environ.get("HEAVY_LOCK", "/opt/data/clips/heavy.lock")
LOG = os.environ.get("HEAVY_LOG", "/opt/data/clips/logs/heavy-log.jsonl")
_fd = None


def _log(row):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def peak_mb():
    kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss + resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return round(kb / (1024 * 1024 if sys.platform == "darwin" else 1024))


def acquire(name, wait_s=None):
    """Take the lock or exit 75. Returns True when this process now holds it."""
    global _fd
    if _fd is not None or os.environ.get("HEAVY_LOCK_HELD") or not os.path.isdir(os.path.dirname(LOCK)):
        return False
    wait_s = float(os.environ.get("HEAVY_WAIT_S", 120)) if wait_s is None else wait_s
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.time() + wait_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= deadline:
                holder = os.pread(fd, 400, 0).decode("utf-8", "replace").strip()
                os.close(fd)
                print(f"BUSY: another heavy job holds {LOCK}: {holder or 'unknown'}\n"
                      f"Waited {wait_s:.0f}s. Rerun this same command when it has finished "
                      f"(heavy jobs run one at a time: 4 GB memory fence).", file=sys.stderr)
                sys.exit(75)
            time.sleep(2)
    t0 = time.time()
    me = {"pid": os.getpid(), "name": name, "since": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
          "cmd": " ".join(sys.argv)[:300]}
    os.ftruncate(fd, 0)
    os.pwrite(fd, json.dumps(me, ensure_ascii=False).encode(), 0)
    _fd = fd
    os.environ["HEAVY_LOCK_HELD"] = "1"
    _log({"ev": "start", **me})

    def done():
        _log({"ev": "end", "pid": me["pid"], "name": name, "s": round(time.time() - t0, 1), "peak_mb": peak_mb()})
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
    atexit.register(done)
    return True
