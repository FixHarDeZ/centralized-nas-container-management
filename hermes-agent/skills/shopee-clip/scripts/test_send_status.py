import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import send_status  # noqa: E402

SCRIPT = os.path.join(HERE, "send_status.py")


def run(*args):
    env = dict(os.environ, HERMES_HOME="/nonexistent")
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env)


def test_same_class_as_clipjob_hashtag_gate():
    src = open(os.path.join(HERE, "clipjob.py"), encoding="utf-8").read()
    pat = re.search(r'CJK_RE = re\.compile\(r"(.*?)"\)', src).group(1)
    for cp in range(0x2E80, 0x10000):
        c = chr(cp)
        assert bool(re.match(f"[{pat[1:-1]}]", c)) == bool(send_status.CJK_RE.match(c)), hex(cp)


def test_emoji_and_thai_pass():
    assert send_status.cjk_hits("ช็อต 2 มาแล้ว → กำลังสแกน 🎬📊💳🔎 ✅ 10+10 = 20 วิ") == []


def test_full_width_and_han_hit():
    assert send_status.cjk_hits("ผ่าน１ช็อต") == [4]
    assert send_status.cjk_hits("ทำ中文") == [2, 3]


def test_check_mode_refuses_without_sending():
    r = run("--check", "ราคา 中 บาท")
    assert r.returncode == 3 and "offset(s) [5]" in r.stderr and "中" not in r.stderr


def test_check_mode_ok():
    r = run("--check", "ผ่าน · เริ่ม gen 🎬")
    assert r.returncode == 0 and r.stdout.startswith("OK")


def test_send_refuses_before_any_token_read():
    r = run("ช็อต 1 เสร็จ（ok）")
    assert r.returncode == 3 and "REFUSED" in r.stderr
