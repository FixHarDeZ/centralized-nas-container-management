import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = "import sys,time,heavylock;print(heavylock.acquire('t'));sys.stdout.flush();time.sleep(float(sys.argv[1]))"


def run(tmp, sleep, wait="0.5", extra=None, bg=False):
    env = dict(os.environ, HEAVY_LOCK=str(tmp / "heavy.lock"), HEAVY_LOG=str(tmp / "log.jsonl"), HEAVY_WAIT_S=wait)
    env.pop("HEAVY_LOCK_HELD", None)
    env.update(extra or {})
    p = subprocess.Popen([sys.executable, "-c", CODE, str(sleep)], cwd=HERE, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if bg:
        assert p.stdout.readline().strip() == "True"
        return p
    out, err = p.communicate()
    return p.returncode, out, err


def test_second_heavy_job_is_refused_then_runs(tmp_path):
    first = run(tmp_path, 3, bg=True)
    rc, out, err = run(tmp_path, 0)
    assert rc == 75 and "BUSY" in err and '"name": "t"' in err
    first.wait()
    rc, out, _ = run(tmp_path, 0)
    assert rc == 0 and out.strip() == "True"
    rows = [json.loads(l) for l in open(tmp_path / "log.jsonl")]
    assert [r["ev"] for r in rows] == ["start", "end", "start", "end"] and rows[1]["peak_mb"] > 0


def test_child_of_the_holder_does_not_lock_again(tmp_path):
    first = run(tmp_path, 2, bg=True)
    rc, out, _ = run(tmp_path, 0, extra={"HEAVY_LOCK_HELD": "1"})
    assert rc == 0 and out.strip() == "False"
    first.wait()


def test_killed_run_leaves_a_start_without_end_and_frees_the_lock(tmp_path):
    first = run(tmp_path, 30, bg=True)
    first.kill(); first.wait()
    rc, out, _ = run(tmp_path, 0)
    assert rc == 0 and out.strip() == "True"
    evs = [json.loads(l)["ev"] for l in open(tmp_path / "log.jsonl")]
    assert evs == ["start", "start", "end"]


def test_no_lock_dir_means_no_lock(tmp_path):
    rc, out, _ = run(tmp_path / "missing", 0)
    assert rc == 0 and out.strip() == "False"
