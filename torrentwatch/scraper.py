"""
TorrentWatch — bearbit.org scraper

Login flow: POST /login.php → session cookie maintained in _client.
If a fetch redirects to login page, re-login is attempted automatically.

HTML selectors are in the SELECTOR_* block below — edit these if the site
changes layout without touching other code. Use GET /api/debug/html?source_id=<id>
to inspect the raw HTML from a running container.
"""

import asyncio
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, urlunparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

import config

_TZ = ZoneInfo(config.TZ)

# ─── Category name mapping (bearbit.org cat IDs) ─────────────────────────────
_CAT_NAMES: dict[str, str] = {
    "901": "H Anime",   "902": "H Game",
    "903": "JP เซ็น",   "904": "JP ไม่เซ็น",
    "905": "ฝรั่ง",     "906": "เอเชียเซ็น",
    "907": "เอเชีย",    "908": "Gay",
    "910": "คลิป",      "911": "รูป",
    "912": "นิตยสาร",
}

def _category_name(cat_id: str) -> str:
    return _CAT_NAMES.get(cat_id, cat_id)

# ─── Selectors — based on actual bearbit.org HTML (verified 2026-05-08) ───────
LOGIN_URL        = f"{config.SITE_BASE_URL}/login.php"
LOGIN_FIELD_USER = "username"
LOGIN_FIELD_PASS = "password"

# Each torrent row has data-category-id; header rows and other <tr>s do not
ROW_SELECTOR = "tr[data-category-id]"

# Column indices (0-based) in each matching <tr>
COL_COVER     = 1   # <td class="poster-column"> → <img src="...">
COL_TITLE     = 2   # <td width="900"> → <a href="details.php?id=X&hashinfo=Y"><b>title
COL_FILES     = 5   # ไฟล์ — plain number
COL_DATE      = 7   # <nobr>DD-MM-YYYY<BR>HH:MM:SS</nobr>
COL_SIZE      = 8   # ขนาด — "2.63 GB" / "380.60 MB"
COL_COMPLETED = 9   # ดาวน์โหลดเสร็จ — completed/snatched count
COL_SEEDS     = 10  # ปล่อย — <span class="green|red">N</span> or plain number
COL_LEECHES   = 11  # ดูด — plain number (may be inside <b><a>N</a></b>)

# Download URL constructed from site_id (id= param in details.php URL)
# Adjust if the server returns 403/redirect — may need dl.php or downloadlink.php
DOWNLOAD_URL_TPL = f"{config.SITE_BASE_URL}/download.php?id={{site_id}}"

LOGIN_URL_MARKERS = ["login.php", "/login", "signin", "register.php"]
# ─────────────────────────────────────────────────────────────────────────────

_client: httpx.AsyncClient | None = None
_login_ok: bool = False


async def init():
    global _client, _login_ok
    _client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; TorrentWatch/1.0)"},
    )
    _login_ok = await _login()
    print(f"[scraper] init — login {'OK' if _login_ok else 'FAILED'}")


async def close():
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def _login() -> bool:
    if not config.SITE_USERNAME or not config.SITE_PASSWORD:
        print("[scraper] WARNING: credentials not set — skipping login")
        return False
    try:
        # Fetch login page first to get any hidden fields / csrf token
        resp = await _client.get(LOGIN_URL)
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form")
        payload = {}
        if form:
            for inp in form.find_all("input", {"type": ["hidden", "text", "password"]}):
                name = inp.get("name", "")
                if name:
                    payload[name] = inp.get("value", "")

        payload[LOGIN_FIELD_USER] = config.SITE_USERNAME
        payload[LOGIN_FIELD_PASS] = config.SITE_PASSWORD

        action = form["action"] if form and form.get("action") else LOGIN_URL
        if not action.startswith("http"):
            action = urljoin(config.SITE_BASE_URL, action)

        print(f"[scraper] login POST → {action} (fields: {list(payload.keys())})")
        resp = await _client.post(action, data=payload)
        print(f"[scraper] login response → {resp.url} (status {resp.status_code})")
        if _is_login_page(resp.text, str(resp.url)):
            print("[scraper] login failed — still on login page after POST")
            return False
        print("[scraper] login OK")
        return True
    except Exception as e:
        print(f"[scraper] login error: {e}")
        return False


def _is_login_page(html: str, url: str) -> bool:
    url_lower = url.lower()
    # URL is the most reliable signal — every page after login has login.php in nav links
    if any(m in url_lower for m in LOGIN_URL_MARKERS):
        return True
    # Fallback: actual <input type="password"> field present means this IS the login form
    return bool(re.search(r'<input[^>]+type=["\']password["\']', html, re.I))


async def _fetch(url: str) -> str | None:
    global _login_ok
    headers = {"Referer": f"{config.SITE_BASE_URL}/"}
    try:
        resp = await _client.get(url, headers=headers)
        if _is_login_page(resp.text, str(resp.url)):
            print("[scraper] session expired — re-logging in")
            _login_ok = await _login()
            if not _login_ok:
                return None
            resp = await _client.get(url, headers=headers)
        return resp.text
    except Exception as e:
        # Connection may be stale after long idle (e.g. overnight pause) — re-login and retry once
        print(f"[scraper] fetch error {url}: {e} — re-logging in and retrying")
        try:
            _login_ok = await _login()
            if not _login_ok:
                return None
            resp = await _client.get(url, headers=headers)
            if _is_login_page(resp.text, str(resp.url)):
                print("[scraper] still on login page after retry — giving up")
                return None
            return resp.text
        except Exception as e2:
            print(f"[scraper] fetch retry failed {url}: {e2}")
            return None


async def relogin() -> bool:
    """Re-establish login session. Call at the start of each scrape cycle to prevent
    stale connections after long idle periods (e.g. overnight pause)."""
    global _login_ok
    _login_ok = await _login()
    return _login_ok


async def fetch_raw_html(url: str) -> str | None:
    """For /api/debug/html — returns the raw page HTML."""
    return await _fetch(url)


async def fetch_login_page_html() -> str | None:
    """For /api/debug/login-page — returns raw login page HTML to inspect form fields."""
    try:
        resp = await _client.get(LOGIN_URL)
        return resp.text
    except Exception as e:
        print(f"[scraper] fetch login page error: {e}")
        return None


async def fetch_detail_html(detail_url: str) -> bytes | None:
    """Fetch a torrent's detail page bytes (TIS-620 encoded) with proper Referer.
    Used by the proxy endpoint to bypass bearbit's anti-hotlink check.
    Re-login is attempted only on exception (stale connection / session drop after
    long idle), never proactively, to avoid triggering bearbit rate limiting.
    """
    global _login_ok
    headers = {"Referer": f"{config.SITE_BASE_URL}/viewbrsb.php"}
    try:
        resp = await _client.get(detail_url, headers=headers)
        if resp.status_code != 200:
            print(f"[scraper] detail fetch {detail_url} → HTTP {resp.status_code}")
        # Return content regardless of status so the user sees bearbit's own page
        # (e.g. session-expired login form, VIP warning, deleted notice)
        return resp.content or None
    except Exception as e:
        # Connection failed (stale pool / session drop after idle) — re-login once and retry
        print(f"[scraper] detail error: {type(e).__name__}: {e} — re-logging in and retrying")
        try:
            _login_ok = await _login()
            if not _login_ok:
                print("[scraper] detail: re-login failed")
                return None
            resp = await _client.get(detail_url, headers=headers)
            if resp.status_code != 200:
                print(f"[scraper] detail retry → HTTP {resp.status_code}")
            return resp.content or None
        except Exception as e2:
            print(f"[scraper] detail retry failed: {type(e2).__name__}: {e2}")
            return None


async def resolve_download_url(detail_url: str) -> str | None:
    """Visit the detail page and find the actual .torrent download link."""
    html = await _fetch(detail_url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    # Look for links containing torrent-download keywords
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"(downloadlink|getfile|dl\.php|\.torrent)", href, re.I):
            url = href if href.startswith("http") else urljoin(config.SITE_BASE_URL, href)
            print(f"[scraper] resolved download URL: {url}")
            return url
    # Fallback: any href with "download" and an id param
    for a in soup.find_all("a", href=re.compile(r"download.*id=\d+", re.I)):
        href = a["href"]
        url = href if href.startswith("http") else urljoin(config.SITE_BASE_URL, href)
        print(f"[scraper] resolved (fallback) download URL: {url}")
        return url
    print(f"[scraper] could not resolve download URL from {detail_url}")
    return None


async def fetch_torrent_bytes(torrent_url: str, detail_url: str = "") -> bytes | None:
    """Download .torrent file bytes. If torrent_url fails, resolve from detail_url.

    Bearbit blocks downloads with non-bearbit Referer — we always set it to the detail
    page (or base URL) so the request looks like it came from within the site.
    """
    if not torrent_url.startswith("http"):
        torrent_url = urljoin(config.SITE_BASE_URL, torrent_url)

    referer = detail_url if detail_url else f"{config.SITE_BASE_URL}/"
    headers = {"Referer": referer}

    try:
        resp = await _client.get(torrent_url, headers=headers)
        ct = resp.headers.get("content-type", "")
        print(f"[scraper] download {torrent_url} → {resp.status_code} {ct}")
        if resp.status_code == 200 and _is_torrent_content(ct, resp.content):
            return resp.content

        # torrent_url failed — resolve from detail page (browser flow: visit detail → click download)
        if detail_url:
            print(f"[scraper] stored URL failed, resolving from detail page…")
            real_url = await resolve_download_url(detail_url)
            if real_url and real_url != torrent_url:
                resp2 = await _client.get(real_url, headers={"Referer": detail_url})
                ct2 = resp2.headers.get("content-type", "")
                print(f"[scraper] resolved download → {resp2.status_code} {ct2}")
                if resp2.status_code == 200 and _is_torrent_content(ct2, resp2.content):
                    return resp2.content
        return None
    except Exception as e:
        print(f"[scraper] torrent download error: {e}")
        return None


async def probe_download_url(torrent_url: str) -> dict:
    """For /api/debug/download-test — returns diagnostic info without downloading."""
    if not torrent_url.startswith("http"):
        torrent_url = urljoin(config.SITE_BASE_URL, torrent_url)
    try:
        resp = await _client.get(torrent_url)
        ct = resp.headers.get("content-type", "")
        preview = resp.content[:200]
        is_torrent = _is_torrent_content(ct, preview)
        return {
            "url_tried":    torrent_url,
            "final_url":    str(resp.url),
            "status":       resp.status_code,
            "content_type": ct,
            "size":         len(resp.content),
            "is_torrent":   is_torrent,
            "preview_text": preview.decode("utf-8", errors="replace")[:200],
        }
    except Exception as e:
        return {"error": str(e), "url_tried": torrent_url}


def _is_torrent_content(content_type: str, preview: bytes) -> bool:
    return (
        "torrent" in content_type
        or "octet-stream" in content_type
        or preview[:13].startswith((b"d8:announce", b"d13:announce"))
    )


def _page_url(base_url: str, page: int) -> str:
    """Build paginated URL: page=0 → base URL, page=N → append ?page=N (preserving existing params)."""
    if page == 0:
        return base_url
    p = urlparse(base_url)
    params = {k: v[0] for k, v in parse_qs(p.query).items()}
    params["page"] = str(page)
    return urlunparse(p._replace(query=urlencode(params)))


async def scrape_source(
    url: str,
    seed_min: int,
    leech_min: int,
    keywords: list[str],
    filter_mode: str = "and",
    on_page=None,            # optional callback(page_num, items_so_far)
    skip_sticky: bool = True,
    completed_min: int = 0,
) -> tuple[list[dict], set[str]]:
    """Scrape all pages until today's items are exhausted.
    Returns (filtered_entries, all_sticky_site_ids_seen_on_site).
    seen_sticky_site_ids contains every sticky site_id found on bearbit this run
    (before any seed/threshold filter) so the caller can sync sticky state in the DB.
    """
    today              = datetime.now(_TZ).strftime("%Y-%m-%d")
    all_items          = []
    seen_sticky_ids: set[str] = set()
    max_pages          = 20   # safety cap

    for page in range(max_pages):
        page_url = _page_url(url, page)
        html     = await _fetch(page_url)
        if not html:
            print(f"[scraper] page {page}: fetch failed, stopping")
            break

        items, found_older, page_sticky_ids = _parse_listing(
            html, page_url, today, seed_min, leech_min, keywords, filter_mode, skip_sticky, completed_min
        )
        all_items.extend(items)
        seen_sticky_ids.update(page_sticky_ids)
        print(f"[scraper] page {page}: {len(items)} pass filter, found_older={found_older}")

        if on_page:
            try:
                on_page(page, len(all_items))
            except Exception:
                pass

        if found_older or not items:
            break

    print(f"[scraper] total {len(all_items)} items across {page + 1} page(s) from {url}")
    return all_items, seen_sticky_ids


def _parse_listing(html: str, base_url: str, today: str, seed_min: int, leech_min: int, keywords: list[str], filter_mode: str = "and", skip_sticky: bool = True, completed_min: int = 0) -> tuple[list[dict], bool, set[str]]:
    """Returns (matching_entries, found_any_older_than_today, seen_sticky_site_ids).
    seen_sticky_site_ids tracks every sticky site_id present on bearbit before filtering.
    """
    soup = BeautifulSoup(html, "html.parser")
    results          = []
    found_older      = False
    seen_sticky_ids: set[str] = set()
    sticky_count     = 0

    rows = soup.select(ROW_SELECTOR)

    for row in rows:
        try:
            entry = _parse_row(row, base_url, today, skip_sticky)
        except Exception as e:
            print(f"[scraper] row parse error: {e}")
            continue

        if not entry:
            continue

        is_sticky = entry.get("is_sticky")

        # Stickies have old dates — bypass the date filter when skip_sticky=False.
        # Track ALL stickies seen on bearbit (before seeds/threshold) so the scheduler
        # can sync which ones are still pinned vs removed.
        if is_sticky:
            sticky_count += 1
            seen_sticky_ids.add(entry["site_id"])
            # Stickies are site-pinned for prominence — bypass seed/leech thresholds.
            # They still go through keyword matching for highlighting in the UI.
            entry["keyword_match"] = _matches_keywords(entry["title"], keywords)
            results.append(entry)
            continue

        if entry["date_posted"] != today:
            found_older = True   # crossed into yesterday — signal to stop paging
            continue

        if entry["seeds"] == 0:
            continue

        kw_match = _matches_keywords(entry["title"], keywords)

        if filter_mode == "or":
            meets_threshold = (
                entry["seeds"] >= seed_min
                or entry["leeches"] >= leech_min
                or (completed_min > 0 and entry.get("completed", 0) >= completed_min)
            )
        else:
            meets_threshold = (
                entry["seeds"] >= seed_min
                and entry["leeches"] >= leech_min
                and (completed_min == 0 or entry.get("completed", 0) >= completed_min)
            )

        if not kw_match and not meets_threshold:
            continue

        entry["keyword_match"] = kw_match
        results.append(entry)

    print(f"[scraper] _parse_listing: {sticky_count} sticky, {len(results) - sticky_count} regular → total {len(results)} results")
    return results, found_older, seen_sticky_ids


def _parse_row(row, base_url: str, today: str, skip_sticky: bool = True) -> dict | None:
    is_sticky = bool(row.find("img", src=re.compile(r"sticky\.gif|heart\.gif|pinned\.gif", re.I)))
    if skip_sticky and is_sticky:
        print(f"[scraper] _parse_row: skip_sticky=True — dropping sticky row")
        return None

    # Extract category
    cat_id = row.get("data-category-id", "")
    category = _category_name(cat_id)

    tds = row.find_all("td", recursive=False)
    if len(tds) < 12:
        if is_sticky:
            print(f"[scraper] _parse_row: STICKY row has only {len(tds)} <td>s (need 12) — dropping")
        return None

    # ── Title & detail URL (col 2: td width=900) ────────────────────────────
    title_td = tds[COL_TITLE]
    title_a = title_td.find("a", href=re.compile(r"details\.php"))
    if not title_a:
        # Fallback: some listing pages use a different PHP filename (e.g. viewno18sbx.php).
        # Find any anchor that has ?id=NNNN AND wraps a <b> tag (bearbit always bolds the title).
        for _a in title_td.find_all("a", href=True):
            if _a.find("b") and re.search(r"\?id=\d+", _a["href"]):
                title_a = _a
                break
    if not title_a:
        if is_sticky:
            print(f"[scraper] _parse_row: STICKY row has no title link — dropping")
        return None

    b_tag = title_a.find("b")
    title = (b_tag or title_a).get_text(strip=True)
    if not title or len(title) < 3:
        if is_sticky:
            print(f"[scraper] _parse_row: STICKY row has empty/short title — dropping")
        return None

    detail_url = urljoin(base_url, title_a["href"])

    # ── Site ID + hashinfo from details.php URL ──────────────────────────────
    m = re.search(r"[?&]id=(\d+)", title_a["href"])
    if not m:
        if is_sticky:
            print(f"[scraper] _parse_row: STICKY row has no id= in href — dropping")
        return None
    site_id = m.group(1)
    m_hash = re.search(r"[?&]hashinfo=(\d+)", title_a["href"])
    hashinfo = m_hash.group(1) if m_hash else ""

    # ── Torrent download URL — try download.php with both id and hashinfo ────
    torrent_url = (
        f"{config.SITE_BASE_URL}/download.php?id={site_id}&hashinfo={hashinfo}"
        if hashinfo else
        f"{config.SITE_BASE_URL}/download.php?id={site_id}"
    )

    # ── Cover image — poster imgs always have absolute URLs (http/https);
    # category icons use relative paths ("pic/categories/...") — skip those.
    cover_url = None
    for img in row.find_all("img"):
        src = img.get("src", "")
        if src.startswith("http") and "categories" not in src and "no_poster" not in src:
            cover_url = src
            break

    # ── Date + Time — row has exactly one <nobr>DD-MM-YYYY<BR>HH:MM:SS</nobr> ─
    date_posted = today
    posted_at = ""
    try:
        nobr = row.find("nobr")
        if nobr:
            raw = nobr.get_text(separator=" ", strip=True)  # "DD-MM-YYYY HH:MM:SS"
            parts_dt = raw.split()
            date_raw = parts_dt[0]   # "DD-MM-YYYY"
            time_raw = parts_dt[1] if len(parts_dt) > 1 else ""
            d_parts = date_raw.split("-")
            if len(d_parts) == 3 and d_parts[2].startswith("20"):
                date_posted = f"{d_parts[2]}-{d_parts[1].zfill(2)}-{d_parts[0].zfill(2)}"
                posted_at = f"{date_posted} {time_raw}".strip()
    except Exception:
        pass

    # ── File count (col 5) ───────────────────────────────────────────────────
    try:
        file_count = _parse_int(tds[COL_FILES].get_text(strip=True))
    except Exception:
        file_count = 0

    # ── File size (col 8) ────────────────────────────────────────────────────
    try:
        file_size = tds[COL_SIZE].get_text(strip=True)  # "2.63 GB" / "380.60 MB"
    except Exception:
        file_size = ""

    # ── Completed downloads (col 9) ──────────────────────────────────────────
    try:
        completed = _parse_int(tds[COL_COMPLETED].get_text(strip=True))
    except Exception:
        completed = 0

    # ── Seeds (col 10) ───────────────────────────────────────────────────────
    try:
        seeds = _parse_int(tds[COL_SEEDS].get_text(strip=True))
    except Exception:
        span = row.select_one("span.green, span.red")
        seeds = _parse_int(span.get_text()) if span else 0

    # ── Leeches (col 11) ─────────────────────────────────────────────────────
    try:
        leeches = _parse_int(tds[COL_LEECHES].get_text(strip=True))
    except Exception:
        leeches = 0

    if is_sticky:
        print(f"[scraper] _parse_row: STICKY parsed OK — site_id={site_id} title={title[:60]}")

    return {
        "site_id":     site_id,
        "title":       title,
        "detail_url":  detail_url,
        "torrent_url": torrent_url,
        "cover_url":   cover_url,
        "seeds":       seeds,
        "leeches":     leeches,
        # Sticky rows carry their original upload date which may be old.
        # Store today so they show up in the Today tab.
        "date_posted": today if is_sticky else date_posted,
        "posted_at":   posted_at,
        "category":    category,
        "file_count":  file_count,
        "file_size":   file_size,
        "completed":   completed,
        "is_sticky":   is_sticky,
    }


def _parse_int(s: str) -> int:
    s = re.sub(r"[^\d]", "", s.strip())
    return int(s) if s else 0


def _matches_keywords(title: str, keywords: list[str]) -> bool:
    title_lower = title.lower()
    return any(kw in title_lower for kw in keywords)


def is_ready() -> bool:
    return _client is not None and _login_ok
