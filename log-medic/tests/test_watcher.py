from app.watcher import RingBuffer, fingerprint, normalize_message


def test_normalize_strips_timestamp():
    line = "2026-07-04T18:03:12.481Z ERROR db timeout"
    assert "2026-07-04" not in normalize_message(line)


def test_normalize_strips_uuid():
    line = "ERROR request 550e8400-e29b-41d4-a716-446655440000 failed"
    assert "550e8400" not in normalize_message(line)


def test_normalize_strips_hex_and_numbers_and_paths():
    line = "ERROR at 0xdeadbeef reading /volume2/docker/foo/bar line 42"
    normalized = normalize_message(line)
    assert "0xdeadbeef" not in normalized
    assert "/volume2/docker/foo/bar" not in normalized
    assert "42" not in normalized


def test_fingerprint_same_for_normalized_equivalent_lines():
    a = fingerprint("torrentwatch", "2026-07-04T18:00:00Z ERROR conn 42 failed")
    b = fingerprint("torrentwatch", "2026-07-04T19:30:00Z ERROR conn 99 failed")
    assert a == b
    assert len(a) == 12


def test_fingerprint_differs_by_container():
    a = fingerprint("torrentwatch", "ERROR boom")
    b = fingerprint("news-feed", "ERROR boom")
    assert a != b


def test_ring_buffer_capture():
    rb = RingBuffer(before=3, after=2)
    for line in ["l1", "l2", "l3", "l4"]:
        rb.push(line)
    excerpt = rb.capture("TRIGGER", ["after1", "after2", "after3"])
    assert excerpt.splitlines() == ["l2", "l3", "l4", "TRIGGER", "after1", "after2"]
