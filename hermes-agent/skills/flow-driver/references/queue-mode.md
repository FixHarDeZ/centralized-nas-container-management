# Queue mode — several clip orders in one sitting

Standing depth for `house-rules.md` → Running an order → "A queue of clips". SKILL.md owns WHEN to overlap the pipelines; this file owns the asset mechanics that make the overlap cheap.

## Asset order — one upload cycle serves the whole queue
- Cut EVERY queued clip's crop BEFORE clip 1's attach, then send all crops in ONE `DOM.setFileInputFiles` call (files=[all]) while the picker's `Uploads` category is active. Uploaded files persist server-side and stay listed under Uploads, so clip N+1's attach later is a plain card click → read the chip count back, with no second upload and no file-chooser-interception cycle. WHY: each upload cycle costs the full interception recipe (`Page.setInterceptFileChooserDialog` → `DOM.getDocument` → `DOM.setFileInputFiles` → change dispatch → 10–15 s wait); one call per queue instead of one per clip removes whole rounds from the run.
- Write clip N+1's prompt into a scratch file DURING clip N's render window, alongside the polls — never ahead of clip N's submit. WHY: render time is 10–25 min of wall clock while prompt writing is minutes; prep before the first submit delays the only render that could already be burning.
- An order arriving mid-run (Fix sends clip N+1 while clip N renders): prep it in that same render window — cut it, upload through the picker while the render runs (page state survives, uploads are server-side), draft the prompt, then do the full submit sequence (re-attach chips → type → chip-count → hit-test → Start generation) as soon as clip N passes verify + log + state.
- Per-clip discipline is unchanged inside a queue: chips clear on EVERY submit, so re-attach clip N+1's already-uploaded image + character chip after its prompt is typed, and read `chips == expected` back before hit-testing Start generation. Hooks, hashtags, frame checks and the review gate also stay per-clip — a queue never downgrades a single-clip rule.

## Character pick inside a queue
- Pick clip N+1's character AFTER clip N's log row is written, and exclude EVERY character already used in this sitting — state's `last_character_used` PLUS each earlier clip of the queue — not only the immediately previous clip. WHY: the state field remembers only the global last clip, so a queue would happily repeat a face the first clip of the same sitting just used, and consecutive posts carrying the same presenter read as a template.
- Random choice within the remaining pool; if Fix names a character for a clip, his pick wins for that clip only.
