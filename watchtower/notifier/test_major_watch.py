"""Self-check for the major-version comparator. Run: python test_major_watch.py"""
import os

os.environ.setdefault("WATCHTOWER_LINE_CHANNEL_ACCESS_TOKEN", "x")
os.environ.setdefault("WATCHTOWER_LINE_USER_ID", "x")

from notifier import newer_major


def test_newer_major():
    assert newer_major("3.0.0", 2) == 3        # ahead → returns new major
    assert newer_major("2.4.0", 2) is None      # same major → no alert
    assert newer_major("1.23.16", 2) is None    # behind → no alert
    assert newer_major("v3.1.0", 2) == 3        # tolerates leading v
    assert newer_major("garbage", 2) is None    # unparseable → no crash
    assert newer_major("10.0.0", 9) == 10       # multi-digit major


if __name__ == "__main__":
    test_newer_major()
    print("OK")
