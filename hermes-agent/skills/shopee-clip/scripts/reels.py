#!/usr/bin/env python3
"""Upload a delivered clip to the Facebook Page as a DRAFT Reel: caption + hashtags + the AI label.

Fix 2026-11-25: "อยากปักตะกร้า affiliate ติด hashtag และติดป้าย ai". The Reels Publishing API (Pages only) takes
a description (hashtags work there) and `is_ai_generated`, but has NO product-tag / affiliate field: the Shopee
basket is added in the Facebook app (Professional dashboard → Monetization → Affiliate Partnerships → Shopee
Affiliates). So the API leaves the Reel as a draft and Fix adds the basket and publishes it himself.

  reels.py draft VIDEO --description-file desc.txt      # FB_PAGE_ID + FB_PAGE_TOKEN from the environment
  -> {"video_id": "...", "state": "DRAFT", "status": {...}} on stdout, exit 0; exit 1 = Graph API error

Flow (developers.facebook.com/documentation/video-api/guides/reels-publishing):
  POST /{page}/video_reels upload_phase=start            -> video_id, upload_url
  POST upload_url (rupload) Authorization: OAuth, offset 0, file_size, body = the mp4
  POST /{page}/video_reels upload_phase=finish video_id video_state=DRAFT description is_ai_generated=true
  GET  /{video_id}?fields=status                         (polled until the upload is processed)
The token travels in POST bodies and headers only, never in a URL or on stdout.
Spec: 9:16, ≥540x960, 3-90 s, H.264, AAC 48 kHz; 30 API posts per Page per 24 h.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GRAPH = "https://graph.facebook.com"
VER = "v27.0"
POLL_S, POLL_MAX = 5, 24           # up to 2 min for Facebook to process the upload


class GraphError(RuntimeError):
    pass


def _call(opener, url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with opener(req, timeout=300) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            err = json.loads(body).get("error") or {}
            msg = f"{err.get('type', 'HTTP')} {err.get('code', e.code)}: {err.get('message', '')}"
        except ValueError:
            msg = f"HTTP {e.code}"
        raise GraphError(msg) from None
    try:
        return json.loads(body or b"{}")
    except ValueError:
        raise GraphError(f"not JSON: {body[:200]!r}") from None


def _form(**kv):
    return urllib.parse.urlencode({k: v for k, v in kv.items() if v is not None}).encode()


def draft(video, description, page_id, token, ai=True, ver=VER, opener=urllib.request.urlopen, sleep=time.sleep):
    """-> {"video_id", "state", "status"}. Raises GraphError."""
    size = os.path.getsize(video)
    base = f"{GRAPH}/{ver}/{page_id}/video_reels"
    got = _call(opener, base, _form(upload_phase="start", access_token=token))
    vid, up = got.get("video_id"), got.get("upload_url")
    if not vid or not up:
        raise GraphError(f"start gave no video_id/upload_url: {sorted(got)}")
    with open(video, "rb") as f:
        body = f.read()
    got = _call(opener, up, body, {"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
                                   "Content-Type": "application/octet-stream"}, "POST")
    if not got.get("success"):
        raise GraphError(f"upload not accepted: {got}")
    got = _call(opener, base, _form(upload_phase="finish", video_id=vid, video_state="DRAFT",
                                    description=description, is_ai_generated="true" if ai else "false",
                                    access_token=token))
    if not got.get("success"):
        raise GraphError(f"finish not accepted: {got}")
    status = {}
    for _ in range(POLL_MAX):
        status = _call(opener, f"{GRAPH}/{ver}/{vid}?fields=status",
                       headers={"Authorization": f"OAuth {token}"}).get("status") or {}
        if status.get("video_status") in ("ready", "error") or \
                (status.get("processing_phase") or {}).get("status") in ("complete", "error"):
            break
        sleep(POLL_S)
    return {"video_id": vid, "state": "DRAFT", "status": status}


def description_for(caption, hashtags):
    """The Reel's text: the short Thai caption, a blank line, the hashtags (Graph turns them into tags)."""
    return "\n\n".join(x.strip() for x in (caption or "", hashtags or "") if x and x.strip())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or argv[0] != "draft":
        print(__doc__, file=sys.stderr)
        return 2
    video = argv[1]
    desc = ""
    if "--description-file" in argv:
        with open(argv[argv.index("--description-file") + 1], encoding="utf-8") as f:
            desc = f.read().strip()
    page, token = os.environ.get("FB_PAGE_ID", "").strip(), os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not page or not token:
        print(json.dumps({"error": "FB_PAGE_ID / FB_PAGE_TOKEN not set"}))
        return 2
    try:
        out = draft(video, desc, page, token)
    except (GraphError, OSError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
