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
   When shot K−1 already has a file, its last frame goes out first as the start-frame photo — 🧑: the newest
   earlier last frame that shows her face; when none does, a line tells Fix to attach no start frame.
   The command's JSON prints ONLY these prompt messages in `packed` — the header, reference photos and
   character portrait are sent by the same run and are not echoed, so a bare pack with a 3-entry `packed`
   list is complete; do not re-run it (that re-spams the chat) just because the output names no photos.
4. Last, the 🤖 offer (Fix 2026-11-23): start shot + ≈credits of the shots left, with the reply-keyboard button
   `🤖 ไอยูกด Flow แทน · <job>`. ingest's start-frame message and ready's gate note carry the same button while a
   shot is left; none after a `fallback` (auto stays locked once Flow failed).

## Fix changes his mind: 🤖 takeover
- His tap arrives as text → `clipjob.py decide --text "<text>"` only. It switches the job to auto (packed shots
  back to `pending`), tells Fix the shots + ≈credits, and prints `next`: `ready` first for a file he already sent
  (still his review — no vision), then flow-driver from the named shot. Typed (`ไอยูทำให้เลย เปลี่ยนใจ`) =
  `clipjob.py production <job> auto`, same effect, no message.
- From then on it is a 🤖 job: per-shot review (router step 10) for every shot YOU render. A file Fix still
  sends for a shot you have not reserved: `ingest` it first; one for a shot already reserved is refused —
  tell him the shot is in your Flow queue and spend nothing twice.
- `takeover: false` + `why` = nothing changed (closed job, already auto, fallback, no shot left): end the turn.

`pack <job> --shot K` resends a single shot. Use it after a 🔁 tap, or when Fix asks for one prompt again.
**A job's FIRST pack must be a bare `pack <job>`** (no `--shot`): the flag suppresses the header AND the
reference photos along with the other shots, so a first pack run with `--shot 1` leaves Fix with a prompt and
nothing to attach in Ingredients. `--shot` is a resend of prompts only — the refs must already be in his chat.

## Taking the files back
- **Confirm the bytes before you ingest.** A reply that names a video but saved no file is not a submission:
  check the disk (`find /opt/data -name '*.mp4' -newermt '-15 minutes'`), and when nothing is there ask Fix to
  resend it as a file replying to that prompt — the shot stays `packed`, never `submitted`, and never answer a
  video reply as if nothing arrived. A reply whose metadata carries a saved path IS the file: ingest it from
  that path.
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
- **Fix's file IS his review (Fix 2026-11-22: "gen prompt แล้วผม reply กลับ ถือว่ารีวิวแล้ว ตีผ่านหมด ไม่ต้องให้ผม
  confirm").** Right after `ingest`: `clipjob.py ready <job> K --raw <file>` — no `--frame`/`--identity`, no
  `idcheck`, no `scan`, no vision call. It runs only the file gates (ffprobe; 🧑 the repeated-line cut and the
  early-CTA check) plus the pixel check (`prodcheck.py`, 0 vision: a product band that changes colour inside
  the shot), approves the shot and sends NO ✅/🔁 keyboard; a message goes to Fix only when one of them found
  something (ℹ️, no buttons — kiiz/cal-d 2026-11-25 shipped box drift with no product read at all). When every shot is approved, go straight to post.
- A new file for an already-approved shot (Fix re-gens on his own) replaces it: `ingest` it the same way.
- `ready` notes anything below 720×1280 or a low bitrate: Telegram re-encoded a "video" send. Tell Fix once to
  send shots as a **file** (📎 → File); a file keeps Flow's original 720p.
- The Bot API download cap is 20 MB. A 10 s 720p shot is far below it. A bigger file fails to download,
  so ask Fix to export at 720p.
- Fix may finish the shots in any order. `ingest` accepts any shot that has been packed. The header asks him
  to gen them IN ORDER with the start-frame photo `ingest` sends back (onesuper-basket 2026-11-22: two shots
  made in parallel drew a 2-compartment and a 3-compartment basket).
- Fix changes the plan before any file (6+4 s failed → one 10 s scene): `clipjob.py reshape <job> --shots 1
  --seconds 10`, rewrite `shot1.txt`, delete the extra shot files, `pack` again (gotg-encore-s2 was cancelled
  and reopened instead).

## Fix's second Flow account (saved characters are per account)
A saved character exists only in the Google account/project that made it; the other account's Characters list
does not have it. `pack` therefore also sends the character's portrait when
`/opt/data/clips/characters/<name>.jpg` exists, and the header tells Fix to attach it as an Ingredient there.
The portraits come from the main account: one crop per roster name from the Characters page (0 credits), saved
under exactly the roster name. No portrait on disk = say so in the header message's follow-up and ask Fix which
account he is on; never swap in another character silently. A face attached as a plain image holds less well
than a saved character (unmeasured here): for a multi-shot 🧑 clip keep all shots on ONE account, and chain
from the previous shot's last frame as usual. The model line in the header (`Omni 1.2 Flash · 720p · x1`) is
what Fix sets in either account. Do NOT follow a pack with a settings restatement: the header carries the model
line and every shot message carries `9:16 · <N> วิ`, so a follow-up line earns its place only with what the pack
does not say — the ≥5 min gap between submits, the per-shot credit estimate, a quota line he asked for.

## Credits
Fix's own submits spend his Flow credits like 🤖. `ingest` records the published rate for the shot's length
(3 credits/s at 720p) with `credits_est`, so the clip-log row has a number (it was `null` on six 📝 jobs of
11-19..22). A different real figure from Fix goes into `--notes`.

## Flow refuses a generation (`สร้างไม่สำเร็จ`)
- **Read the error dialog yourself with a vision call before telling Fix anything about credits.** The gateway's
  auto-description of a Thai screenshot inverted `คุณจะได้รับเครดิตคืน` into "will NOT receive a refund" once,
  and the wrong number then went out as a status line that had to be retracted. A policy refusal
  (`การสร้างนี้อาจละเมิดนโยบายของเรา`) IS refunded: it costs nothing, and the answer is never "budget N extra credits".
- **First move = the model, not the prompt: ask Fix to switch that shot to Omni 1.1 Flash** (Settings → model; same
  prompt, same chips), and back to 1.2 for the next shot — Flow keeps the last model per project. ps2-hdd-175-pres shot 2 (2026-11-24): an
  unchanged retry, plain gradient tiles instead of game covers, no character chip, no start frame — all refused on
  1.2 (80 min); Fix tried 1.1 and it rendered first time. 1.1 = 1.5 cr/s (6 s = 9): ingest that file with
  `--credits 9` (the default records the 1.2 estimate). Omni 1.1 leaves Flow on 2026-12-05; after that the
  fallback model is Veo 3.1 Lite (cost unread — ask Fix to read its credit line).
- Refused on 1.1 too: ONE change per round — the single structural difference from a shot of the clip that passed
  (most often the action that forces Flow to render an IP-bearing asset: real game covers, brand art), edit only
  that, `pack --shot K`, and tell Fix which words changed and why. Testing without the start frame =
  `pack --shot K --no-start-frame` (it refuses while the prompt still asks for one); a plain re-pack says to attach
  the frame again (pack prints a `warn` for it), so that round would not test what you think it tests.

## Deliver acks (moved from the router, 2026-11-22)
`deliver` refuses while the report has a flag Fix has not decided. Tell him each flag with its frame time; he
picks "ส่งแบบนี้" or regen. As-is = `--ack "<flag text>=<his call>"` (logged), ONE `--ack` per flag: they append
and each splits on its first `=`, so `|`-joining two flags in one `--ack` leaves the second undecided and the
refusal repeats.
