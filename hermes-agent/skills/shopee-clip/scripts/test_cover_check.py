import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cover_check", os.path.join(HERE, "cover_check.py"))
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


@pytest.mark.parametrize("text", ["6,990.-", "100.-", "฿1,290", "ราคา 990", "SALE", "50% OFF", "-30%", "ลด 20%",
                                  "ส่งฟรี", "CODE: SHOP10", "1,290 บาท", "199฿"])
def test_price_and_promo_text_hits(text):
    assert cc.price_hits(text), text


@pytest.mark.parametrize("text", ["97%", "10:08", "HUAWEI WATCH FIT 5", "2000 ml", "OPPO Pad mini 2", "3in1",
                                  "IP68", "PS5", "40th Anniversary"])
def test_product_screen_and_label_text_passes(text):
    assert cc.price_hits(text) == [], text


def test_spec_strings_cover_every_typed_field():
    s = {"title": ["A", "B"], "sub": "C", "badge": "D", "chips": ["E", "F"], "circles": [{"label": "G"}]}
    assert sorted(cc.spec_strings(s)) == list("ABCDEFG")


def test_missing_glyphs_finds_tofu():
    from PIL import ImageFont
    f = os.path.join(HERE, "..", "..", "gameplay-clips", "fonts", "Mali-Bold.ttf")
    font = ImageFont.truetype(f, 60, layout_engine=ImageFont.Layout.BASIC)
    assert cc.missing_glyphs(["ขายดี AB"], font) == []
    assert cc.missing_glyphs(["ขาย中"], font) == ["中"]
