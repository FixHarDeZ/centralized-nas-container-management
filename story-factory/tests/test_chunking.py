from app import chunking

# Thai prose uses the space as its sentence break; there is no full stop.
THAI = (
    "เมกะโลดอนเป็นฉลามยักษ์ที่เคยว่ายอยู่ในมหาสมุทร "
    "นักบรรพชีวินวิทยาพบฟันของมันกระจายอยู่ทั่วโลก "
    "แต่ไม่เคยมีใครพบโครงกระดูกที่สมบูรณ์เลยสักครั้ง"
)


def test_short_text_is_one_chunk():
    chunks = chunking.split(THAI, 5000)
    assert len(chunks) == 1
    assert chunks[0].text == THAI
    assert not chunks[0].forced


def test_every_chunk_fits_the_cap():
    chunks = chunking.split(THAI * 40, 5000)
    assert len(chunks) > 1
    assert all(chunk.byte_length <= 5000 for chunk in chunks)


def test_no_text_is_lost():
    chunks = chunking.split(THAI * 40, 5000)
    rejoined = "".join(chunk.text.replace(" ", "") for chunk in chunks)
    assert rejoined == (THAI * 40).replace(" ", "")


def test_cuts_land_on_sentence_boundaries_not_byte_offsets():
    # A boundary cut means no chunk starts or ends mid-sentence, i.e. every
    # chunk's edges coincide with pieces of the original.
    chunks = chunking.split(THAI * 40, 600)
    pieces = [p for p in (THAI * 40).split(" ") if p]
    for chunk in chunks:
        assert chunk.text.split(" ")[0] in pieces
        assert chunk.text.split(" ")[-1] in pieces


def test_packing_is_greedy_so_the_call_count_stays_low():
    # Fewer calls means fewer prosody resets, which is the accepted cost in
    # ADR 0012 — so a lazy splitter that emits one sentence per call is wrong.
    chunks = chunking.split(THAI * 40, 5000)
    total = len((THAI * 40).encode("utf-8"))
    assert len(chunks) <= total // 5000 + 2


def test_an_unbreakable_run_is_flagged_rather_than_silently_cut():
    chunks = chunking.split("ก" * 4000, 900)
    assert all(chunk.byte_length <= 900 for chunk in chunks)
    assert any(chunk.forced for chunk in chunks)


def test_newlines_are_boundaries_too():
    chunks = chunking.split("บทที่หนึ่ง\nบทที่สอง", 40)
    assert [c.text for c in chunks] == ["บทที่หนึ่ง", "บทที่สอง"]
