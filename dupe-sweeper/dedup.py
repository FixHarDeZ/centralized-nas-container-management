"""Duplicate video finder core — code extraction + filesystem walk.

Ported from the standalone avdedup.py CLI. Code-extraction logic is unchanged
(already validated against real filenames); the only addition here is skipping
Synology/junk directories during the walk.
"""

import os
import re

# ---------- video extensions ----------
DEFAULT_EXTS = {
    "mp4", "mkv", "avi", "wmv", "ts", "m4v", "mov", "iso",
    "mpg", "mpeg", "rmvb", "rm", "flv", "vob", "m2ts", "strm",
}

# ---------- directories never walked ----------
# @eaDir: Synology thumbnail/index dirs (everywhere). #recycle: DSM recycle bin.
# .dupe-sweeper-trash: our own recycle folder (else trashed files resurface as dups).
SKIP_DIRS = {"@eaDir", "#recycle", ".dupe-sweeper-trash"}

# ---------- tokens that are codec/quality, not a code ----------
BLOCKLIST = {
    "X264", "X265", "H264", "H265", "HEVC", "AVC", "AAC", "AC3", "EAC3",
    "DTS", "FLAC", "MP3", "MP4", "MKV", "AVI", "WMV", "WEB", "HDR", "SDR",
    "BLURAY", "WEBDL", "WEBRIP", "HDRIP", "WORLD",
    "HD", "FHD", "UHD", "SD", "VIDEO", "MOVIE", "SCENE", "FULL", "PART",
    "DISC", "FILE", "MOSAIC",
}


def _strip0(digits: str) -> str:
    """Drop leading zeros, keep at least one digit (SSNI-00618 == SSNI-618)."""
    s = digits.lstrip("0")
    return s if s else "0"


def extract_code(name: str):
    """Return (code, part_marker); code=None when nothing recognisable."""
    upper = name.upper()

    # shared leading separator (or start) consumes the delimiter, then the
    # marker itself. A/B/C/D single-letter part only when it's the last token
    # before the extension (ipx-177.A.mp4) to avoid matching random letters.
    part = None
    mpart = re.search(
        r"(?:[-_ .]|^)(CD\d|PART\d|PT\d|DISC\d|[ABCD](?=\.\w+$))", upper
    )
    if mpart:
        part = mpart.group(1)

    # 1) FC2
    m = re.search(r"FC2[-_ ]?PPV[-_ ]?(\d{5,8})", upper)
    if m:
        return f"FC2-PPV-{m.group(1)}", part

    # 2) HEYZO (handles heyzo_hd_2451)
    m = re.search(r"HEYZO[-_ ]?(?:HD[-_ ]?)?(\d{3,5})", upper)
    if m:
        return f"HEYZO-{_strip0(m.group(1))}", part

    # 3) caribbean / 1pondo / 10musume date-sequence: 010112-123 or 123456_789
    m = re.search(r"(?<!\d)(\d{6})[-_](\d{2,4})(?!\d)", upper)
    if m:
        return f"{m.group(1)}-{m.group(2)}", part

    # 4) standard LETTERS-DIGITS (ABP-123, SSNI-1234, MIDE-800 ...)
    for mm in re.finditer(r"([A-Z]{2,6})[-_ ]?(\d{2,5})", upper):
        letters, digits = mm.group(1), mm.group(2)
        if letters in BLOCKLIST:
            continue
        return f"{letters}-{_strip0(digits)}", part

    return None, part


RES_RE = re.compile(r"(2160P|1440P|1080P|720P|480P|4K|8K|UHD)", re.I)


def res_guess(name: str) -> str:
    m = RES_RE.search(name)
    if not m:
        return "-"
    r = m.group(1).upper()
    return {"4K": "2160p", "UHD": "2160p", "8K": "4320p"}.get(r, r.lower())


def scan(root: str, exts: set):
    """Walk root, return a list of file dicts. Skips junk dirs in-place."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext not in exts:
                continue
            full = os.path.join(dirpath, fn)
            try:
                st = os.stat(full)
            except OSError:
                continue
            code, part = extract_code(fn)
            files.append({
                "path": full,
                "name": fn,
                "size": st.st_size,
                "mtime": st.st_mtime,
                "code": code,
                "part": part,
                "res": res_guess(fn),
            })
    return files
