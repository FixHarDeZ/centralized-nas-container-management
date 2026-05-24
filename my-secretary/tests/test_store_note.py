import os
import tempfile
import store


def _fresh_store(tmpdir):
    """Re-initialise store with a clean temp directory."""
    store._state["pending"] = {}
    store._state["pending_general"] = {}
    store._state["pending_note"] = {}
    store._state["history"] = {}
    store.init(tmpdir)


def test_pending_note_starts_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        assert not store.has_pending_note("U001")
        assert store.get_pending_note("U001") is None


def test_pending_note_set_and_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending_note("U001", {"phase": "asking_topic"})
        assert store.has_pending_note("U001")
        assert store.get_pending_note("U001") == {"phase": "asking_topic"}


def test_pending_note_overwrite():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending_note("U001", {"phase": "asking_topic"})
        store.set_pending_note("U001", {"phase": "waiting_content", "page_id": "abc", "title": "T"})
        assert store.get_pending_note("U001")["phase"] == "waiting_content"


def test_pending_note_pop():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending_note("U001", {"phase": "asking_topic"})
        val = store.pop_pending_note("U001")
        assert val == {"phase": "asking_topic"}
        assert not store.has_pending_note("U001")


def test_pending_note_pop_missing_returns_none():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        assert store.pop_pending_note("U_MISSING") is None


def test_pending_note_persists_to_disk():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending_note("U002", {"phase": "waiting_content", "page_id": "p1", "title": "Saved"})

        # Simulate restart: wipe in-memory state and reload from disk
        store._state["pending_note"] = {}
        store.init(tmpdir)

        assert store.has_pending_note("U002")
        assert store.get_pending_note("U002")["title"] == "Saved"


def test_pending_note_does_not_affect_pending():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending("U003", {"op": "write"})
        store.set_pending_note("U003", {"phase": "asking_topic"})

        store.pop_pending_note("U003")
        assert store.has_pending("U003")
        assert not store.has_pending_note("U003")
