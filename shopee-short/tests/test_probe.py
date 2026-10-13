import hashlib
import json

import shopee_probe as probe


def test_signature_is_sha256_of_appid_timestamp_body_secret():
    body = b'{"query":"{x}"}'
    expected = hashlib.sha256(b"123" + b"1700000000" + body + b"s3cret").hexdigest()

    assert probe.sign("123", 1700000000, body, "s3cret") == expected


def test_request_hashes_the_exact_bytes_it_sends():
    req = probe.build_request("https://example.invalid/graphql", "123", "s3cret", "{x}", now=1700000000)

    header = req.get_header("Authorization")
    assert header.startswith("SHA256 Credential=123,Timestamp=1700000000,Signature=")
    signature = header.rsplit("=", 1)[1]
    assert signature == probe.sign("123", 1700000000, req.data, "s3cret")
    assert json.loads(req.data) == {"query": "{x}"}


def test_variables_are_part_of_the_signed_body():
    req = probe.build_request("https://example.invalid/graphql", "1", "s", "q", {"a": 1}, now=1)

    assert json.loads(req.data) == {"query": "q", "variables": {"a": 1}}


def test_secret_never_appears_in_the_request():
    req = probe.build_request("https://example.invalid/graphql", "123", "s3cret", "{x}", now=1)

    assert b"s3cret" not in req.data
    assert "s3cret" not in req.get_header("Authorization")


def test_short_link_query_carries_sub_ids():
    query, variables = probe.short_link_query("https://shopee.co.th/product/1/2", ["probe"])

    assert "generateShortLink" in query
    assert variables == {"url": "https://shopee.co.th/product/1/2", "subIds": ["probe"]}


def test_missing_credentials_exit_with_a_message(monkeypatch, capsys):
    monkeypatch.delenv("SHOPEE_APP_ID", raising=False)
    monkeypatch.delenv("SHOPEE_SECRET", raising=False)

    assert probe.main(["schema"]) == 2
    assert "SHOPEE_APP_ID" in capsys.readouterr().err
