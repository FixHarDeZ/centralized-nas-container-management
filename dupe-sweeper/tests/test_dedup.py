import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import dedup  # noqa: E402
import recycle  # noqa: E402


@pytest.mark.parametrize("name,code", [
    ("SSNI-618.mp4", "SSNI-618"),
    ("SSNI-00618-1080p.mkv", "SSNI-618"),          # zero-pad == unpadded
    ("[FC2-PPV-1234567] whatever.mp4", "FC2-PPV-1234567"),
    ("heyzo_hd_2451.mp4", "HEYZO-2451"),            # not HD-2451
    ("010112-123-caribbean.wmv", "010112-123"),
    ("123456_789.mp4", "123456-789"),
    ("ABP-123 [1080p][x264].mkv", "ABP-123"),
    ("279UTSU-123.mp4", "UTSU-123"),                # studio-number prefix stripped
])
def test_extract_code(name, code):
    assert dedup.extract_code(name)[0] == code


def test_blocklist_not_a_code():
    # pure codec/quality tokens must not be mistaken for a code
    assert dedup.extract_code("movie.x264.1080p.mkv")[0] is None


@pytest.mark.parametrize("name,part", [
    ("MIDE-800-cd1.mp4", "CD1"),
    ("MIDE-800-cd2.mp4", "CD2"),
    ("ipx-177.A.mp4", "A"),
    ("ipx-177.B.mp4", "B"),
])
def test_part_marker(name, part):
    assert dedup.extract_code(name)[1] == part


def test_skip_dirs_present():
    for junk in ("@eaDir", "#recycle", ".dupe-sweeper-trash"):
        assert junk in dedup.SKIP_DIRS


# ---------- delete = trust boundary ----------

def test_validate_rejects_outside_root(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "etc_passwd"
    outside.write_text("x")
    with pytest.raises(ValueError):
        recycle.validate([str(outside)], [str(root)])


def test_validate_rejects_traversal(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    with pytest.raises(ValueError):
        recycle.validate([str(root / ".." / "escape.mp4")], [str(root)])


def test_recycle_moves_within_same_tree(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    f = root / "SSNI-618.mp4"
    f.write_bytes(b"0123456789")
    trash = root / ".dupe-sweeper-trash"
    res = recycle.recycle([str(f)], [str(root)], str(trash))
    assert res["freed"] == 10
    assert res["results"][0]["ok"]
    assert not f.exists()
    # file now lives somewhere under trash
    moved = list(trash.rglob("SSNI-618.mp4"))
    assert len(moved) == 1


def test_recycle_all_or_nothing(tmp_path):
    # one bad path in the batch => nothing moves
    root = tmp_path / "media"
    root.mkdir()
    good = root / "keep.mp4"
    good.write_bytes(b"x")
    with pytest.raises(ValueError):
        recycle.recycle([str(good), "/etc/hosts"], [str(root)], str(root / ".t"))
    assert good.exists()  # good file untouched because validation failed first


# ---------- rename guard ----------

def test_rename_ok(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    f = root / "old.mp4"
    f.write_bytes(b"x")
    dest = recycle.rename(str(f), "new.mp4", [str(root)])
    assert dest == str(root / "new.mp4")
    assert (root / "new.mp4").exists() and not f.exists()


@pytest.mark.parametrize("bad", ["../escape.mp4", "sub/x.mp4", "..", ".", ""])
def test_rename_rejects_bad_name(tmp_path, bad):
    root = tmp_path / "media"
    root.mkdir()
    f = root / "old.mp4"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        recycle.rename(str(f), bad, [str(root)])
    assert f.exists()


def test_rename_no_overwrite(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "a.mp4").write_bytes(b"x")
    (root / "b.mp4").write_bytes(b"y")
    with pytest.raises(ValueError):
        recycle.rename(str(root / "a.mp4"), "b.mp4", [str(root)])


def test_rename_outside_root_rejected(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    outside = tmp_path / "x.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        recycle.rename(str(outside), "y.mp4", [str(root)])


# ---------- empty-trash config guard (catastrophic op) ----------

def test_empty_trash_refuses_wrong_basename(tmp_path):
    # TRASH_DIR fat-fingered to a real media dir must refuse
    root = tmp_path / "porn"
    root.mkdir()
    keep = root / "keep.mp4"
    keep.write_bytes(b"x")
    with pytest.raises(ValueError):
        recycle.empty_trash(str(root), [str(root)])
    assert keep.exists()


def test_list_trash_groups_by_batch(tmp_path):
    root = tmp_path / "media"
    trash = root / recycle.TRASH_BASENAME
    (trash / "2026-01-01_120000").mkdir(parents=True)
    (trash / "2026-01-01_120000" / "SSNI-618.mp4").write_bytes(b"0123456789")
    files = recycle.list_trash(str(trash))
    assert len(files) == 1
    assert files[0]["name"] == "SSNI-618.mp4"
    assert files[0]["size"] == 10
    assert files[0]["batch"] == "2026-01-01_120000"


def test_restore_roundtrip(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    f = root / "sub" / "SSNI-618.mp4"
    f.parent.mkdir()
    f.write_bytes(b"0123456789")
    trash = root / recycle.TRASH_BASENAME
    recycle.recycle([str(f)], [str(root)], str(trash))
    assert not f.exists()
    moved = list(trash.rglob("SSNI-618.mp4"))[0]
    dest = recycle.restore(str(moved), [str(root)], str(trash))
    assert dest == str(f)
    assert f.exists() and f.read_bytes() == b"0123456789"
    assert not moved.exists()  # emptied batch dir pruned


def test_restore_no_overwrite(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    f = root / "a.mp4"
    f.write_bytes(b"x")
    trash = root / recycle.TRASH_BASENAME
    recycle.recycle([str(f)], [str(root)], str(trash))
    f.write_bytes(b"new")  # something reclaimed the original name
    moved = list(trash.rglob("a.mp4"))[0]
    with pytest.raises(ValueError):
        recycle.restore(str(moved), [str(root)], str(trash))


def test_restore_rejects_outside_trash(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    trash = root / recycle.TRASH_BASENAME
    trash.mkdir()
    outside = root / "keep.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        recycle.restore(str(outside), [str(root)], str(trash))
    assert outside.exists()


def test_empty_trash_ok(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    trash = root / recycle.TRASH_BASENAME
    (trash / "batch").mkdir(parents=True)
    (trash / "batch" / "gone.mp4").write_bytes(b"0123456789")
    stats = recycle.empty_trash(str(trash), [str(root)])
    assert stats["count"] == 1 and stats["size"] == 10
    assert trash.exists() and not any(trash.iterdir())  # folder kept, contents gone


# ---------- mask signature ----------

def test_mask_signature_order_independent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib
    import config as _c
    importlib.reload(_c)
    import db
    importlib.reload(db)
    a, b = "/media/x/SSNI-618.mp4", "/media/x/ssni-00618.mkv"
    assert db.mask_signature([a, b]) == db.mask_signature([b, a])
    assert db.mask_signature([a, b]) != db.mask_signature([a])


# ---------- deletion audit log ----------

def test_log_deletions_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import importlib
    import config as _c
    importlib.reload(_c)
    import db
    importlib.reload(db)
    db.init_db()
    db.log_deletions("2026-07-22_120000", [
        {"path": "/media/x/SSNI-618.mp4", "ok": True, "size": 10},
        {"path": "/media/x/bad.mp4", "ok": False, "size": 0, "error": "boom"},
    ])
    rows = db.list_deletions()
    assert len(rows) == 2
    assert {r["name"] for r in rows} == {"SSNI-618.mp4", "bad.mp4"}
    bad = next(r for r in rows if r["name"] == "bad.mp4")
    assert bad["ok"] == 0 and bad["error"] == "boom"
