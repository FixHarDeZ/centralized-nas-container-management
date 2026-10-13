#!/usr/bin/env python3
"""Phase 0 probe for the Shopee Affiliate Open API (TH). Stdlib only.

Runs on the workstation, not the NAS. Credentials come from the environment
(export them from the vault, see shopee-short/.notes/00_INDEX.md) and are
never printed:

    python3 shopee-short/scripts/shopee_probe.py schema

Commands:
    schema              introspect the fields productOfferV2 / conversionReport return
    link <url> [subId]  generateShortLink with a subId (default "probe")
    offers <keyword>    productOfferV2, 5 results
    report [days]       conversionReport for the last N days (default 7)

The TH endpoint is inferred from the .com.br / .com.my pattern; override with
SHOPEE_API_URL if the dashboard shows a different one. Field names below come
from community SDKs, so run `schema` first — a wrong field fails the whole query.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://open-api.affiliate.shopee.co.th/graphql"

SHORT_LINK = """mutation ($url: String!, $subIds: [String]) {
  generateShortLink(input: {originUrl: $url, subIds: $subIds}) { shortLink }
}"""

OFFERS = """query ($keyword: String, $limit: Int) {
  productOfferV2(keyword: $keyword, limit: $limit) {
    nodes { itemId productName priceMin commissionRate sales ratingStar imageUrl offerLink productLink }
    pageInfo { page limit hasNextPage }
  }
}"""

REPORT = """query ($start: Int64, $end: Int64) {
  conversionReport(purchaseTimeStart: $start, purchaseTimeEnd: $end, limit: 50) {
    nodes { purchaseTime clickTime totalCommission utmContent }
    pageInfo { limit hasNextPage scrollId }
  }
}"""

SCHEMA = """{
  queryType { fields { name args { name type { name kind ofType { name } } } type { name ofType { name } } } }
  mutationType { fields { name args { name type { name kind ofType { name } } } } }
}"""


def sign(app_id: str, timestamp: int, body: bytes, secret: str) -> str:
    return hashlib.sha256(app_id.encode() + str(timestamp).encode() + body + secret.encode()).hexdigest()


def build_request(url: str, app_id: str, secret: str, query: str, variables: dict | None = None,
                  now: int | None = None) -> urllib.request.Request:
    payload = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    # Serialise once: the signature covers these exact bytes, and a body
    # re-encoded after hashing is the usual cause of error 10020.
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    ts = int(time.time()) if now is None else now
    return urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={app_id},Timestamp={ts},Signature={sign(app_id, ts, body, secret)}",
    })


def short_link_query(url: str, sub_ids: list[str]) -> tuple[str, dict]:
    return SHORT_LINK, {"url": url, "subIds": sub_ids}


def type_fields_query(type_name: str) -> str:
    return f'{{ __type(name: "{type_name}") {{ name fields {{ name type {{ name kind ofType {{ name }} }} }} }} }}'


def call(url: str, app_id: str, secret: str, query: str, variables: dict | None = None) -> dict:
    req = build_request(url, app_id, secret, query, variables)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"http_status": e.code, "body": e.read().decode(errors="replace")}


def main(argv: list[str]) -> int:
    app_id, secret = os.environ.get("SHOPEE_APP_ID"), os.environ.get("SHOPEE_SECRET")
    if not app_id or not secret:
        print("set SHOPEE_APP_ID and SHOPEE_SECRET", file=sys.stderr)
        return 2
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    url = os.environ.get("SHOPEE_API_URL", DEFAULT_URL)
    cmd, args = argv[0], argv[1:]

    if cmd == "schema":
        out = {"root": call(url, app_id, secret, SCHEMA)}
        for name in ("ProductOfferV2", "ConversionReport"):
            out[name] = call(url, app_id, secret, type_fields_query(name))
    elif cmd == "link" and args:
        out = call(url, app_id, secret, *short_link_query(args[0], [args[1] if len(args) > 1 else "probe"]))
    elif cmd == "offers" and args:
        out = call(url, app_id, secret, OFFERS, {"keyword": " ".join(args), "limit": 5})
    elif cmd == "report":
        end = int(time.time())
        out = call(url, app_id, secret, REPORT, {"start": end - 86400 * int(args[0] if args else 7), "end": end})
    else:
        print(__doc__, file=sys.stderr)
        return 2

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
