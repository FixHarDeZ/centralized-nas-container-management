import json
import re

from bs4 import BeautifulSoup


def _dedupe(entries: list[dict]) -> list[dict]:
    out, seen = [], set()
    for e in entries:
        if e["code"] in seen:
            continue
        seen.add(e["code"])
        out.append(e)
    return out


def fetch_api_seria(src: dict, text: str) -> list[dict]:
    data = json.loads(text)
    return [
        {"code": it["code"], "reward": (it.get("rewards") or "").strip()}
        for it in data.get("codes", [])
        if it.get("status") == "OK"
    ]


def fetch_table_status(src: dict, text: str) -> list[dict]:
    soup = BeautifulSoup(text, "html.parser")
    code_re = re.compile(src["code_regex"])
    out = []
    for row in soup.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        code, status = cells[0], cells[1].lower()
        if not code_re.match(code):
            continue
        if "expired" not in status:
            out.append({"code": code, "reward": ""})
    return _dedupe(out)


def fetch_section_regex(src: dict, text: str) -> list[dict]:
    soup = BeautifulSoup(text, "html.parser")
    if src.get("scope_selector"):
        scope = " ".join(
            el.get_text(" ", strip=True) for el in soup.select(src["scope_selector"])
        )
    else:
        scope = soup.get_text(" ", strip=True)
    code_re = re.compile(src["code_regex"])
    return _dedupe(
        [{"code": m.group(0), "reward": ""} for m in code_re.finditer(scope)],
    )


PARSERS = {
    "api_seria": fetch_api_seria,
    "table_status": fetch_table_status,
    "section_regex": fetch_section_regex,
}


def parse(src: dict, text: str) -> list[dict]:
    return PARSERS[src["type"]](src, text)
