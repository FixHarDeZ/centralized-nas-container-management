import os

import config
import db


def _add(slug="s1", **kw):
    args = dict(slug=slug, title="T", tags="tag1,tag2", pages=20,
                file_size=1000, source_url="https://x/s1/")
    args.update(kw)
    return db.add_title(**args)


def test_add_and_get(data_dir):
    tid = _add()
    row = db.get_title(tid)
    assert row["slug"] == "s1"
    assert row["status"] == "new"
    assert row["expires_at"] is not None


def test_known_slugs_includes_deleted(data_dir):
    tid = _add("s1")
    _add("s2")
    db.purge_title(tid)
    assert db.known_slugs() == {"s1", "s2"}


def test_keep_clears_expiry(data_dir):
    tid = _add()
    assert db.keep_title(tid)
    row = db.get_title(tid)
    assert row["status"] == "kept"
    assert row["expires_at"] is None


def test_purge_removes_files_and_tombstones(data_dir):
    tid = _add()
    open(db.cbz_path(tid), "wb").write(b"x")
    open(db.cover_path(tid), "wb").write(b"x")
    assert db.purge_title(tid)
    assert not os.path.exists(db.cbz_path(tid))
    assert not os.path.exists(db.cover_path(tid))
    row = db.get_title(tid)
    assert row["status"] == "deleted"
    assert row["file_size"] is None


def test_expired_ids(data_dir):
    tid = _add("old")
    with db._connect() as conn:
        conn.execute("UPDATE titles SET expires_at='2000-01-01T00:00:00+07:00' WHERE id=?", (tid,))
    _add("fresh")
    kept = _add("kept-old")
    db.keep_title(kept)
    assert db.expired_ids() == [tid]


def test_list_filter_and_stats(data_dir):
    _add("a")
    tid = _add("b")
    db.keep_title(tid)
    assert len(db.list_titles()) == 2
    assert [r["slug"] for r in db.list_titles(status="kept")] == ["b"]
    s = db.stats()
    assert s["new"]["count"] == 1
    assert s["kept"]["count"] == 1
    assert s["kept"]["size"] == 1000


def test_scrape_log(data_dir):
    assert db.last_scrape() is None
    db.log_scrape(5, 3)
    db.log_scrape(2, 0, error="boom")
    last = db.last_scrape()
    assert last["found"] == 2
    assert last["error"] == "boom"
