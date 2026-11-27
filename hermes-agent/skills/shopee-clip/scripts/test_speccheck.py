"""speccheck.py: listing spec numbers vs the numbers Fix's photos print (no OCR here)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import speccheck as s


def test_spec_tokens_read_number_and_unit():
    got = s.spec_tokens("คีมเชื่อมลวด 800A · 2,000mAh · 20V MAX · 1.5 A · 999VF · 3 วัตต์ · ๑๒V")
    assert got == {"A": {"800", "1.5"}, "MAH": {"2000"}, "V": {"20", "12"}, "W": {"3"}}   # 999VF: not a spec
    assert s.spec_tokens("รุ่น A1 2A2 Ver.2") == {}
    assert s.spec_tokens("คีมเชื่อมลวด800A ด้ามจับ") == {"A": {"800"}}         # Thai glued to the number (Shopee titles)
    assert s.hits("ใช้คีมเชื่อมลวด800Aตัวนี้", ["800A"]) == ["800A"]


def test_conflict_only_when_no_listing_value_is_printed():
    """keem-herm-loud-800a 2026-11-27: listing 800A, the holder in Fix's photo prints 300A."""
    title = s.spec_tokens("คีมเชื่อมลวด 800A ด้ามจับถนัดมือ")
    assert s.conflicts(title, s.spec_tokens("300A ELECTRODE HOLDER")) == {"A": {"listing": ["800"], "photos": ["300"]}}
    assert s.conflicts(title, s.spec_tokens("300A 500A 800A")) == {}            # a variant chart: no conflict
    assert s.conflicts(title, s.spec_tokens("USB 2A charger")) == {}            # another order of magnitude: noise
    assert s.conflicts(title, s.spec_tokens("ไม่มีตัวเลข")) == {}               # the photos name no amps
    assert s.conflicts({}, s.spec_tokens("300A")) == {}                         # the title names no amps


def test_banned_tokens_and_hits_in_digits_and_thai_words():
    conf = {"A": {"listing": ["800"], "photos": ["300"]}}
    ban = s.banned(conf)
    assert ban == ["300A", "800A"] and s.banned(conf, ["800a"]) == ["300A"]
    assert s.hits("ใช้คีมเชื่อมลวด 800A ตัวนี้มาสักพัก", ban) == ["800A"]
    assert s.hits("คีมแปดร้อยแอมป์ ด้ามจับถนัดมือ", ban) == ["800A"]
    assert s.hits("คีม 300 แอมป์", ban) == ["300A"]
    assert s.hits("คีมเชื่อมลวดตัวนี้ ทนความร้อนสูง", ban) == []
    assert s.hits("ใช้มา 800 วัน", ban) == []
    assert "listing says 800A, the photos print 300A" in s.describe(conf)
