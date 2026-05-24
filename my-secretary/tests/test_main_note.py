import main


def test_note_intent_thai_exact():
    assert main._is_note_intent("จดหน่อย") is True
    assert main._is_note_intent("จดให้หน่อย") is True
    assert main._is_note_intent("จดให้ด้วย") is True
    assert main._is_note_intent("จดด้วย") is True
    assert main._is_note_intent("เตรียมจด") is True
    assert main._is_note_intent("ช่วยจด") is True
    assert main._is_note_intent("จดไว้") is True
    assert main._is_note_intent("บันทึกให้หน่อย") is True


def test_note_intent_english():
    assert main._is_note_intent("note please") is True
    assert main._is_note_intent("please note") is True
    assert main._is_note_intent("help me note") is True
    assert main._is_note_intent("take a note") is True
    assert main._is_note_intent("make a note") is True


def test_note_intent_case_insensitive():
    assert main._is_note_intent("NOTE PLEASE") is True
    assert main._is_note_intent("Take A Note") is True


def test_note_intent_substring_match():
    assert main._is_note_intent("จดหน่อยนะคะ") is True
    assert main._is_note_intent("ช่วยจดให้หน่อยได้ไหม") is True
    assert main._is_note_intent("can you please note this for me") is True


def test_note_intent_no_match():
    assert main._is_note_intent("สวัสดี") is False
    assert main._is_note_intent("ขอ user pass jira") is False
    assert main._is_note_intent("ค่าน้ำ") is False
    assert main._is_note_intent("/clear") is False
    assert main._is_note_intent("") is False
