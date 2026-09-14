from app.sources import Passage, check, rewrite_note


def test_a_sourced_claim_may_be_stated_as_fact():
    verdict = check([Passage("ฟันของมันยาวกว่า 17 เซนติเมตร", source="Smithsonian")])
    assert verdict


def test_an_unsourced_claim_stated_as_fact_is_rejected():
    verdict = check([Passage("ชาวประมงพบมันเมื่อคืนที่ผ่านมา")])
    assert not verdict
    assert "stated as fact" in verdict.problems[0]


def test_hearsay_phrasing_rescues_an_unsourced_claim():
    verdict = check([Passage("เล่ากันว่าชาวประมงเคยเห็นเงาดำใต้เรือ")])
    assert verdict


def test_a_figure_without_a_source_is_rejected_even_when_hedged():
    # Hedging does not make an invented year harmless. This is the concrete
    # failure measured in shorts-factory: fabricated numbers.
    verdict = check([Passage("เล่ากันว่าเรือลำนั้นหายไปเมื่อปี 1928")])
    assert not verdict
    assert any("figure" in problem for problem in verdict.problems)


def test_thai_digits_and_era_markers_count_as_figures():
    for text in ("เล่ากันว่ามีคน ๗ คน", "เล่ากันว่าเกิดขึ้นใน พ.ศ. นั้น"):
        assert not check([Passage(text)])


def test_every_problem_is_reported_not_just_the_first():
    verdict = check(
        [
            Passage("เล่ากันว่ามันยังมีชีวิตอยู่"),
            Passage("มันตายไปแล้วเมื่อ 3 ล้านปีก่อน"),
            Passage("นักวิทยาศาสตร์ยืนยันแล้ว"),
        ],
    )
    assert len(verdict.problems) == 3
    assert "passage 2" in verdict.problems[0]


def test_rewrite_note_restates_the_rule():
    note = rewrite_note(check([Passage("มันยังมีชีวิตอยู่")]))
    assert "Source note" in note
    assert "เล่ากันว่า" in note


def test_an_unsplittable_run_is_a_rewrite_not_a_dead_story():
    # tts.voice_chapter refuses a run with no sentence boundary inside the
    # request cap. Caught here, the Chapter is rewritten; caught there, the
    # Story dies after every other Chapter has already been paid for.
    long_run = "ก" * 4000  # 12,000 bytes, no boundary anywhere
    verdict = check([Passage(long_run, "แหล่งจริง")], limit=5000)
    assert not verdict
    assert "5000" in verdict.problems[0]


def test_the_length_rule_is_off_unless_a_limit_is_given():
    long_run = "ก" * 4000
    assert check([Passage(long_run, "แหล่งจริง")])
