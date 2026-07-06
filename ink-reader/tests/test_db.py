import os

import config
import db


def _add(slug="s1", **kw):
    args = dict(slug=slug, title="T", tags="tag1,tag2", pages=20, file_size=1000, source_url="https://x/s1/")
    args.update(kw)
    return db.add_title(**args)


def test_add_and_get(data_dir):
    db.init_db()
    tid = _add()
    row = db.get_title(tid)
    assert row["slug"] == "s1"
    assert row["status"] == "new"
    assert row["expires_at"] is not None


def test_known_slugs_includes_deleted(data_dir):
    db.init_db()
    tid = _add("s1")
    _add("s2")
    db.purge_title(tid)
    assert db.known_slugs() == {"s1", "s2"}


def test_keep_clears_expiry(data_dir):
    db.init_db()
    tid = _add()
    assert db.keep_title(tid)
    row = db.get_title(tid)
    assert row["status"] == "kept"
    assert row["expires_at"] is None
