from app import story


def test_a_job_survives_a_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    job = story.new("หัวข้อ", ["บทหนึ่ง", "บทสอง"])
    job.chapters.append(story.Done("บทหนึ่ง", [{"text": "เล่ากันว่า…", "source": ""}]))
    job.save()

    back = story.Job.load(job.workdir)
    assert back.subject == "หัวข้อ"
    assert back.next_index == 1
    assert back.chapters[0].prose == "เล่ากันว่า…"
    assert not back.voiced(0)


def test_voiced_needs_the_file_not_just_the_number(tmp_path, monkeypatch):
    # A kill between writing the wav and saving the index leaves the two
    # disagreeing; the file is the truth because it is what gets paid for.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    job = story.new("x", ["a"])
    job.chapters.append(story.Done("a", [{"text": "t", "source": ""}], duration=12.0))
    assert not job.voiced(0)
    job.audio(0).write_bytes(b"RIFF")
    assert job.voiced(0)


def test_unfinished_skips_finished_and_abandoned(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    old = story.new("เก่า", ["a"])
    old.outcome = "finished"
    old.save()
    # Workdirs are named by the second, so force distinct names.
    dropped = story.Job(subject="ทิ้ง", titles=["a"], workdir=story.root() / "2", outcome="abandoned")
    dropped.save()
    live = story.Job(subject="ค้าง", titles=["a"], workdir=story.root() / "3")
    live.save()

    assert story.unfinished().subject == "ค้าง"


def test_prune_keeps_the_newest_finished_and_never_the_live_one(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for n in range(1, 5):
        story.Job(subject=str(n), titles=["a"], workdir=story.root() / str(n), outcome="finished").save()
    story.Job(subject="live", titles=["a"], workdir=story.root() / "0").save()

    assert story.prune(keep=2) == 2
    left = sorted(p.name for p in story.root().iterdir())
    assert left == ["0", "3", "4"]
