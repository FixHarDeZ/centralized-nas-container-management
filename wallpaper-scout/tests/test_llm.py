import json

import app.llm as llm


class _FakeMimoResponse:
    def __init__(self, text):
        self._text = text

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


def test_expand_query_parses_json_array(mocker):
    mocker.patch(
        "app.llm.http_client.post",
        return_value=_FakeMimoResponse(json.dumps(["IU", "Lee Ji-eun", "아이유"])),
    )

    terms = llm.expand_query("IU")
    assert terms == ["IU", "Lee Ji-eun", "아이유"]


def test_expand_query_falls_back_to_topic_on_bad_json(mocker):
    mocker.patch("app.llm.http_client.post", return_value=_FakeMimoResponse("not json"))

    terms = llm.expand_query("Wuthering Waves")
    assert terms == ["Wuthering Waves"]


def test_expand_query_falls_back_to_anthropic_when_mimo_raises(mocker):
    mock_post = mocker.patch("app.llm.http_client.post", side_effect=RuntimeError("mimo down"))
    fake_client = mocker.Mock()
    fake_client.messages.create.return_value = mocker.Mock(
        content=[mocker.Mock(text=json.dumps(["Genshin Impact", "原神"]))]
    )
    mocker.patch("app.llm.anthropic.Anthropic", return_value=fake_client)

    terms = llm.expand_query("Genshin Impact")

    # Proves MiMo was tried first (and failed) before Anthropic fallback ran,
    # not the other way around.
    mock_post.assert_called_once()
    fake_client.messages.create.assert_called_once()
    assert terms == ["Genshin Impact", "原神"]


def test_expand_query_returns_topic_when_mimo_returns_empty_list(mocker):
    mocker.patch(
        "app.llm.http_client.post",
        return_value=_FakeMimoResponse(json.dumps([])),
    )

    terms = llm.expand_query("SomeTopic")
    assert terms == ["SomeTopic"]


def test_expand_query_falls_back_to_topic_when_both_providers_raise(mocker):
    mocker.patch("app.llm.http_client.post", side_effect=RuntimeError("mimo down"))
    fake_client = mocker.Mock()
    fake_client.messages.create.side_effect = RuntimeError("anthropic down too")
    mocker.patch("app.llm.anthropic.Anthropic", return_value=fake_client)
    mocker.patch(
        "app.llm._anthropic_retry",
        side_effect=lambda fn, retries=3: (_ for _ in ()).throw(RuntimeError("anthropic down too")),
    )

    terms = llm.expand_query("Genshin Impact")
    assert terms == ["Genshin Impact"]


def test_expand_query_caps_at_five_terms(mocker):
    mocker.patch(
        "app.llm.http_client.post",
        return_value=_FakeMimoResponse(json.dumps(["a", "b", "c", "d", "e", "f", "g"])),
    )

    terms = llm.expand_query("a")
    assert len(terms) == 5
