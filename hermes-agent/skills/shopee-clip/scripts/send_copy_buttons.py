#!/usr/bin/env python3
"""Send the hashtags + basket link as ONE Telegram message with tap-to-copy buttons.

Fix (2026-11-05): "ตอนส่งคลิปอยากได้ปุ่ม copy link แบบเดียวกับ hashtag". Telegram shows no
copy control on a URL inside a code block (tested A/B/C: plain <pre>, <pre> with a language
header, and the Hermes markdown fence, none of them worked for the link). The Bot API
InlineKeyboardButton.copy_text works (Fix confirmed variant D).

Usage:
  send_copy_buttons.py "<hashtags>" "<basket link>" [chat_id] [product label]
Exit 0 only when Telegram answers ok:true with a message_id and both buttons are echoed back.
copy_text is limited to 256 chars; hashtags are capped at 150 by house rule anyway.
"""
import importlib.util, json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("send_clip", os.path.join(HERE, "send_clip.py"))
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    tags, link = sys.argv[1].strip(), sys.argv[2].strip()
    chat = sys.argv[3] if len(sys.argv) > 3 else "8663614341"
    label = sys.argv[4] if len(sys.argv) > 4 else ""
    if not link.startswith("https://"):
        sys.exit("link must be https://")
    if len(tags) > 256 or len(link) > 256:
        sys.exit("copy_text max 256 chars")
    text = (f"📋 {label}\n\n" if label else "📋 ") + f"Hashtags:\n{tags}\n\n🛒 ปักตะกร้า:\n{link}"
    body = {"chat_id": chat, "text": text, "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [
                [{"text": "🛒 Copy ลิงก์ตะกร้า", "copy_text": {"text": link}}],
                [{"text": "#️⃣ Copy hashtags", "copy_text": {"text": tags}}]]}}
    req = urllib.request.Request(f"https://api.telegram.org/bot{sc.read_token()}/sendMessage",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "body": getattr(e, "read", lambda: b"")()[:300].decode("utf-8", "replace")}))
        return 1
    kb = r.get("result", {}).get("reply_markup", {}).get("inline_keyboard", [])
    copies = [b[0].get("copy_text", {}).get("text") for b in kb]
    ok = bool(r.get("ok") and r["result"].get("message_id") and copies == [link, tags])
    print(json.dumps({"ok": ok, "message_id": r.get("result", {}).get("message_id"), "buttons": copies}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
