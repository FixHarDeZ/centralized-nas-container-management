# Prompt pack (📝): Fix runs Flow, IU does everything else

Use this when Fix picks 📝 at Q3, or when 🤖 falls back. Evidence for preferring it: one 2026-11-09 run passed
when Fix submitted the same prompt and reference from his own browser. The bot-driven submits were
flagged `unusual activity`. That is one run and the cause is unconfirmed, so 📝 is the safe default,
not proof that 🤖 cannot work.

## What `clipjob.py pack <job>` sends
1. One header message: product, which shots are left, how to use the pack, and the fallback reason if any.
2. Every reference photo (`--ref` from `new`) as a Telegram photo, so Fix can save it and attach it in
   Flow → Ingredients.
3. For each shot K that needs generating (pending or regen_approved), one message:
   `[ช็อต K · <job>] ช็อต K/N · 9:16 · 10 วิ`, then the prompt in a `<pre>` block (tap to copy on the phone).
   When shot K−1 already has a file, its last frame goes out first as the start-frame photo.

`pack <job> --shot K` resends a single shot. Use it after a 🔁 tap, or when Fix asks for one prompt again.

## Taking the files back
- Hermes passes the replied-to message text to you. Read it, find `[ช็อต K · job]`, and run
  `clipjob.py ingest <job> <file> --reply-text "<that text>"`. The tag, not the message id or the file name,
  maps the file to its shot.
- A video with no reply context means ask which shot it is (buttons `ช็อต 1 … ช็อต N`), then run `--shot K`.
  Never guess from the order or the file name: a wrong guess puts a good shot in the wrong slot.
  **Exception: a job with ONE shot has exactly one slot** — ingest the bare video with `--shot 1` and ask
  nothing; with N>1 the ask stands, because only then can a guess land in the wrong slot.
- The same bytes can arrive twice — a bare send, then the identical mp4 again as a reply to the prompt.
  `md5sum` both before ingesting: equal hashes mean one render, so ingest only the copy carrying the
  `[ช็อต K · job]` tag and drop the other. Do not start a frame review on a bare video either — the
  status/reply context decides the slot, the file name never does.
- The ✅/🔁 tap comes back as plain text and `clipjob.py decide --text` accepts ONLY the button label
  verbatim: `✅ ผ่าน ช็อต K · <job>` / `🔁 gen ใหม่ ช็อต K · <job>`. A paraphrase (`✅ ช็อต K · <job>`)
  is REFUSED — copy the label off the keyboard message, don't retype it from memory.
- `ready` flags anything below 720×1280 or a low bitrate. That means Telegram re-encoded a "video" send.
  Tell Fix once to send shots as a **file** (📎 → File); a file keeps Flow's original 720p.
- The Bot API download cap is 20 MB. A 10 s 720p shot is far below it. A bigger file fails to download,
  so ask Fix to export at 720p.
- Fix may finish the shots in any order. `ingest` accepts any shot that has been packed.

## Fix's second Flow account (saved characters are per account)
A saved character exists only in the Google account/project that made it; the other account's Characters list
does not have it. `pack` therefore also sends the character's portrait when
`/opt/data/clips/characters/<name>.jpg` exists, and the header tells Fix to attach it as an Ingredient there.
The portraits come from the main account: one crop per roster name from the Characters page (0 credits), saved
under exactly the roster name. No portrait on disk = say so in the header message's follow-up and ask Fix which
account he is on; never swap in another character silently. A face attached as a plain image holds less well
than a saved character (unmeasured here): for a multi-shot 🧑 clip keep all shots on ONE account, and chain
from the previous shot's last frame as usual. The model line in the header (`Omni 1.2 Flash · 720p · x1`) is
what Fix sets in either account.

## Credits
Fix's own submits spend his Flow credits exactly like 🤖, and IU cannot read them. Do not report a credit
figure for 📝 shots: `deliver` logs `credits: null` unless every attempt carried a number.
