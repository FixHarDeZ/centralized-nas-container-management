import os
import tempfile

import pytest


@pytest.fixture
def env(monkeypatch):
    data_dir = tempfile.mkdtemp()
    photos_dir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", data_dir)
    monkeypatch.setenv("PHOTOS_ROOT", photos_dir)
    import importlib
    import app.db as db_module
    import app.scheduler as scheduler_module
    importlib.reload(db_module)
    importlib.reload(scheduler_module)
    db_module.init_db()
    return scheduler_module, db_module, photos_dir


def test_slugify(env):
    scheduler, _, _ = env
    assert scheduler.slugify("Wuthering Waves") == "wuthering-waves"
    assert scheduler.slugify("IU!!") == "iu"


def test_schedule_topic_passes_next_run_time(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)
    topic = db.get_topic(topic_id)

    mock_sched = mocker.MagicMock()
    scheduler.schedule_topic(mock_sched, topic)

    from datetime import datetime

    next_run_time = mock_sched.add_job.call_args.kwargs["next_run_time"]
    assert isinstance(next_run_time, datetime)


def test_first_cycle_uses_toplist_and_marks_backfilled(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)

    mocker.patch("app.scheduler.llm.expand_query", return_value=["IU"])
    search_mock = mocker.patch(
        "app.scheduler.wallhaven.search",
        return_value=[{"id": "abc", "path": "https://x/abc.jpg", "file_type": "image/jpeg"}],
    )
    mocker.patch("app.scheduler.wallhaven.download_image", return_value=b"fake-bytes")

    scheduler.run_topic_cycle(topic_id)

    assert search_mock.call_args.args[2] == "toplist"
    topic = db.get_topic(topic_id)
    assert topic["backfilled"] == 1
    assert topic["search_terms"] == ["IU"]
    assert db.download_exists(topic_id, "mobile", "abc") is True

    written = os.path.join(photos_dir, "mobile", "iu", "abc.jpg")
    assert os.path.exists(written)
    with open(written, "rb") as f:
        assert f.read() == b"fake-bytes"


def test_first_cycle_marks_backfilled_even_if_toplist_finds_nothing(env, mocker):
    # A niche topic can genuinely have zero results in Wallhaven's toplist
    # window (a real observed case, not hypothetical) — that's a valid,
    # completed backfill attempt, not a failure to retry. Otherwise the
    # topic gets stuck retrying an empty toplist forever and never reaches
    # date_added, where real results usually exist.
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)

    mocker.patch("app.scheduler.llm.expand_query", return_value=["IU"])
    mocker.patch("app.scheduler.wallhaven.search", return_value=[])

    scheduler.run_topic_cycle(topic_id)

    topic = db.get_topic(topic_id)
    assert topic["backfilled"] == 1


def test_first_cycle_marks_backfilled_even_if_all_downloads_fail(env, mocker):
    # Accepted tradeoff: if search finds items but every download throws
    # (e.g. a transient CDN outage), this cycle's batch is lost, but the
    # topic still advances to date_added next cycle rather than retrying
    # toplist forever — a much more common failure mode (empty toplist) is
    # what this gate exists to fix, at the cost of this rarer one.
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)

    mocker.patch("app.scheduler.llm.expand_query", return_value=["IU"])
    mocker.patch(
        "app.scheduler.wallhaven.search",
        return_value=[{"id": "abc", "path": "https://x/abc.jpg", "file_type": "image/jpeg"}],
    )
    mocker.patch("app.scheduler.wallhaven.download_image", side_effect=Exception("boom"))

    scheduler.run_topic_cycle(topic_id)

    topic = db.get_topic(topic_id)
    assert topic["backfilled"] == 1
    assert db.download_exists(topic_id, "mobile", "abc") is False


def test_second_cycle_uses_date_added_and_skips_existing(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)
    db.set_search_terms(topic_id, ["IU"])
    db.mark_backfilled(topic_id)
    db.record_download(topic_id, "mobile", "abc", "abc.jpg")

    mocker.patch("app.scheduler.llm.expand_query")  # should not be called again
    search_mock = mocker.patch(
        "app.scheduler.wallhaven.search",
        return_value=[
            {"id": "abc", "path": "https://x/abc.jpg", "file_type": "image/jpeg"},
            {"id": "def", "path": "https://x/def.jpg", "file_type": "image/jpeg"},
        ],
    )
    download_mock = mocker.patch("app.scheduler.wallhaven.download_image", return_value=b"fake-bytes")

    scheduler.run_topic_cycle(topic_id)

    assert search_mock.call_args.args[2] == "date_added"
    scheduler.llm.expand_query.assert_not_called()
    download_mock.assert_called_once_with("https://x/def.jpg")
    assert db.download_exists(topic_id, "mobile", "def") is True


def test_cycle_stops_at_max_new_per_cycle(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=1)
    db.set_search_terms(topic_id, ["IU"])
    db.mark_backfilled(topic_id)

    mocker.patch(
        "app.scheduler.wallhaven.search",
        return_value=[
            {"id": "one", "path": "https://x/one.jpg", "file_type": "image/jpeg"},
            {"id": "two", "path": "https://x/two.jpg", "file_type": "image/jpeg"},
        ],
    )
    download_mock = mocker.patch("app.scheduler.wallhaven.download_image", return_value=b"fake-bytes")

    scheduler.run_topic_cycle(topic_id)

    download_mock.assert_called_once()
    assert db.download_exists(topic_id, "mobile", "one") is True
    assert db.download_exists(topic_id, "mobile", "two") is False


def test_disabled_topic_is_skipped(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)
    db.update_topic(topic_id, enabled=0)
    search_mock = mocker.patch("app.scheduler.wallhaven.search")

    scheduler.run_topic_cycle(topic_id)

    search_mock.assert_not_called()


def test_unknown_purpose_is_skipped_not_crashed(env, mocker):
    # Stale data case: a topic created before "laptop" was removed from
    # PURPOSE_PRESETS still has it in its purposes list — must skip that
    # purpose (not KeyError) and still process the remaining valid ones.
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["laptop", "mobile"], frequency_per_day=1, max_new_per_cycle=5)

    mocker.patch("app.scheduler.llm.expand_query", return_value=["IU"])
    search_mock = mocker.patch(
        "app.scheduler.wallhaven.search",
        return_value=[{"id": "abc", "path": "https://x/abc.jpg", "file_type": "image/jpeg"}],
    )
    mocker.patch("app.scheduler.wallhaven.download_image", return_value=b"fake-bytes")

    downloaded = scheduler.run_topic_cycle(topic_id)

    assert downloaded == 1
    search_mock.assert_called_once_with(["IU"], "mobile", "toplist")
    assert db.download_exists(topic_id, "mobile", "abc") is True


def test_default_source_is_wallhaven_only(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)
    assert db.get_topic(topic_id)["sources"] == ["wallhaven"]

    mocker.patch("app.scheduler.llm.expand_query", return_value=["IU"])
    mocker.patch("app.scheduler.wallhaven.search", return_value=[])
    booru_search = mocker.patch("app.scheduler.booru.search")

    scheduler.run_topic_cycle(topic_id)
    booru_search.assert_not_called()


def test_multi_source_routes_and_shares_quota(env, mocker):
    # Topic with both sources: wallhaven fills first (list order), booru fills
    # the remainder of the shared per-purpose cap. Ids stay namespaced.
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("Wuthering Waves", ["pc"], frequency_per_day=1, max_new_per_cycle=3, sources=["wallhaven", "booru"])
    db.set_search_terms(topic_id, ["Wuthering Waves"])
    db.mark_backfilled(topic_id)

    mocker.patch("app.scheduler.wallhaven.search", return_value=[
        {"id": "wh1", "path": "https://x/wh1.jpg"},
        {"id": "wh2", "path": "https://x/wh2.jpg"},
    ])
    mocker.patch("app.scheduler.wallhaven.download_image", return_value=b"w")
    mocker.patch("app.scheduler.booru.search", return_value=[
        {"id": "yr:5", "path": "https://x/5.png"},
        {"id": "kc:6", "path": "https://x/6.png"},
    ])
    mocker.patch("app.scheduler.booru.download_image", return_value=b"b")

    downloaded = scheduler.run_topic_cycle(topic_id)

    assert downloaded == 3  # 2 wallhaven + 1 booru (cap=3)
    assert db.download_exists(topic_id, "pc", "wh1")
    assert db.download_exists(topic_id, "pc", "wh2")
    assert db.download_exists(topic_id, "pc", "yr:5")
    assert not db.download_exists(topic_id, "pc", "kc:6")
    # namespaced id -> colon replaced in filename
    assert os.path.exists(os.path.join(photos_dir, "pc", "wuthering-waves", "yr-5.png"))


def test_reddit_query_string_url_yields_clean_extension(env, mocker):
    # reddit preview URLs carry ?width=...&s=... — filename must be "<id>.jpg",
    # not "<id>.jpg?width=...". Guards the ext-strip in _run_purpose.
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5, sources=["reddit"])
    db.set_search_terms(topic_id, ["IU"])
    db.mark_backfilled(topic_id)

    mocker.patch("app.scheduler.reddit.search", return_value=[
        {"id": "rd:abc", "path": "https://preview.redd.it/abc.jpg?width=1080&s=deadbeef"},
    ])
    mocker.patch("app.scheduler.reddit.download_image", return_value=b"pic")

    scheduler.run_topic_cycle(topic_id)

    assert os.path.exists(os.path.join(photos_dir, "mobile", "iu", "rd-abc.jpg"))


def test_send_daily_summary_sends_aggregated_message(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)
    from datetime import date
    today = date.today().isoformat()
    db.record_download(topic_id, "mobile", "abc", "abc.jpg")
    db.record_download(topic_id, "mobile", "def", "def.jpg")

    sent = mocker.patch("app.scheduler.notifier.send")
    scheduler.send_daily_summary()

    assert sent.called
    text = sent.call_args.args[0]
    assert "IU" in text
    assert "2" in text
