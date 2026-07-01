import json
import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def db(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)
    db_module.init_db()
    return db_module


def test_create_and_get_topic(db):
    topic_id = db.create_topic("IU", ["mobile", "pc"], frequency_per_day=2, max_new_per_cycle=5)
    topic = db.get_topic(topic_id)
    assert topic["query"] == "IU"
    assert topic["purposes"] == ["mobile", "pc"]
    assert topic["frequency_per_day"] == 2
    assert topic["max_new_per_cycle"] == 5
    assert topic["enabled"] == 1
    assert topic["backfilled"] == 0
    assert topic["search_terms"] is None


def test_list_topics(db):
    db.create_topic("IU", ["mobile"], 1, 5)
    db.create_topic("Genshin Impact", ["laptop", "pc"], 3, 5)
    topics = db.list_topics()
    assert len(topics) == 2
    assert {t["query"] for t in topics} == {"IU", "Genshin Impact"}


def test_update_topic(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    db.update_topic(topic_id, enabled=0, frequency_per_day=4)
    topic = db.get_topic(topic_id)
    assert topic["enabled"] == 0
    assert topic["frequency_per_day"] == 4


def test_delete_topic(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    db.delete_topic(topic_id)
    assert db.get_topic(topic_id) is None


def test_set_search_terms_and_mark_backfilled(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    db.set_search_terms(topic_id, ["IU", "Lee Ji-eun", "아이유"])
    db.mark_backfilled(topic_id)
    topic = db.get_topic(topic_id)
    assert topic["search_terms"] == ["IU", "Lee Ji-eun", "아이유"]
    assert topic["backfilled"] == 1


def test_download_dedup(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    assert db.download_exists(topic_id, "mobile", "wallhaven-abc") is False
    db.record_download(topic_id, "mobile", "wallhaven-abc", "wallhaven-abc.jpg")
    assert db.download_exists(topic_id, "mobile", "wallhaven-abc") is True
    # same id under a different purpose is a separate row, not a dedup hit
    assert db.download_exists(topic_id, "pc", "wallhaven-abc") is False


def test_daily_download_counts(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    db.record_download(topic_id, "mobile", "wallhaven-abc", "wallhaven-abc.jpg")
    db.record_download(topic_id, "mobile", "wallhaven-def", "wallhaven-def.jpg")
    from datetime import date
    today = date.today().isoformat()
    counts = db.daily_download_counts(today)
    assert counts == {"IU": 2}
