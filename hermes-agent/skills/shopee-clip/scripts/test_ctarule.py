import importlib.util, os, sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ctarule
import post_presenter as pp
import test_clipjob as tc
cj = tc.cj

LATE = "ลิงก์อยู่ใต้คลิปนะจ๊ะ ไปดูรายละเอียดกันได้เลย กลิ่นก็มีให้เลือกเพียบ"
GOOD = "กลิ่นก็มีให้เลือกเพียบ ลิงก์อยู่ใต้คลิปนะจ๊ะ ไปดูรายละเอียดกันได้เลย"


def test_a_selling_point_after_the_link_line_is_named():
    assert "กลิ่นก็มีให้เลือกเพียบ" in ctarule.problem(LATE)
    assert ctarule.problem(GOOD) == ""
    assert ctarule.problem("พิกัดลิงก์ใต้คลิปนะจ๊ะ! รีบเลยนะ") == ""
    assert ctarule.problem("หอมมาก สดชื่นทั้งวัน") == ""          # no link line: Fix ruled it out, nothing to order


def test_voiceover_block_is_read_from_a_prompt():
    prompt = 'Scene…\nAudio (Thai voiceover): "%s"\nON-SCREEN TEXT: NONE' % LATE
    assert ctarule.voiceover(prompt) == LATE
    assert ctarule.link_span(ctarule.phrases(LATE)) == (0, 0)


@pytest.fixture(autouse=True)
def _no_prompt_left_behind():
    yield                                         # test_clipjob's jobs share one workdir
    for f in os.listdir(cj.WORK) if os.path.isdir(cj.WORK) else []:
        d = os.path.join(cj.WORK, f)
        for n in os.listdir(d) if os.path.isdir(d) else []:
            if n.startswith("shot") and n.endswith(".txt"):
                os.remove(os.path.join(d, n))


def _final_prompt(j, script):
    os.makedirs(j["workdir"], exist_ok=True)
    k = len(j["shots"])
    open(os.path.join(j["workdir"], f"shot{k}.txt"), "w", encoding="utf-8").write(
        'x\nAudio (Thai voiceover): "%s"\n' % script)
    return k


def test_reserve_refuses_the_final_shot_before_credits(monkeypatch):
    j = tc.job(shots=1, prod="auto")
    k = _final_prompt(j, LATE)
    with pytest.raises(cj.Refused, match="ประโยคลิงก์ต้องปิดท้าย"):
        cj.reserve(j, k, None, 1000.0)
    monkeypatch.setenv("CTA_ORDER_OK", "1")                       # Fix's own call
    cj.reserve(j, k, None, 1000.0)


def test_reserve_passes_a_script_that_ends_on_the_link_line():
    j = tc.job(shots=1, prod="auto")
    cj.reserve(j, _final_prompt(j, GOOD), None, 1000.0)


def test_pack_refuses_too():
    j = tc.job(shots=1, prod="prompt")
    _final_prompt(j, LATE)
    with pytest.raises(cj.Refused, match="ประโยคลิงก์ต้องปิดท้าย"):
        cj.cmd_pack(j, None, True)


def test_a_cut_up_brand_name_is_one_word_again():
    known = {"ครีม", "อาบน้ำ", "กุ", "บุ", "โฉมใหม่", "ก็", "ดี"}
    assert pp.glue_names(["ครีม", "อาบน้ำ", "โช", "กุ", "บุ", "สซึ", "โฉมใหม่"], known) == \
        ["ครีม", "อาบน้ำ", "โชกุบุสซึ", "โฉมใหม่"]
    assert pp.glue_names(["ก็", "ดี", "ครีม"], known) == ["ก็", "ดี", "ครีม"]      # short known words stay apart
