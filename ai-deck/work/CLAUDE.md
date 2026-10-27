# AI Deck work folder

You are running on a NAS, driven from a phone. The person reading your output
is on a small screen: keep replies short, and put results in files.

## Folders

- `in/`  — source material the user dropped in (pptx, xlsx, docx, pdf, images, notes). Read-only by convention: never modify or delete anything here.
- `out/` — every deliverable goes here, nothing else does. The user downloads from this folder on the phone.
- Anything scratch goes in `/tmp`, not in `in/` or `out/`.

## Output rules

- File names: `YYYY-MM-DD-<short-topic>.<ext>` (e.g. `2026-09-15-q3-review.pptx`). Never overwrite an existing file in `out/` — add `-v2`, `-v3`.
- Decks: use the `pptx` skill. After writing the file, render it to images and **look at every slide** before saying it is done. Fix overflow, tofu, and misaligned text yourself.
- Spreadsheets: use the `xlsx` skill. Formulas over hard-coded values; recalc and check for `#REF!`/`#VALUE!` before finishing.
- Documents: use the `docx` skill.
- Thai text is common here. Thai fonts are installed (TLWG family); use them in decks so the preview matches what PowerPoint on the phone will show.

## Issue tracker and triage labels

This section is the tracker config that `to-prd`, `to-spec`, `to-issues`,
`to-tickets` and `triage` ask for. `/setup-matt-pocock-skills` is not
installed on the desk — use this instead, and do not tell the user to run it.

- **Tracker: local markdown files.** The desk has no GitHub/Linear login.
- **Flat in `out/`.** The phone's file drawer lists only the top-level files
  of `out/`, so a subfolder (including `.scratch/<feature>/issues/`) is
  invisible to the user. One file per issue/ticket:
  `out/YYYY-MM-DD-<feature-slug>-NN-<slug>.md`, `NN` from `01` in dependency
  order (blockers first). A PRD or spec is `out/YYYY-MM-DD-<feature-slug>-prd.md`
  / `-spec.md`; its issues name that file as their Parent.
- **Labels are lines at the top of the file**: `**Status:** <state>` and, once
  triaged, `**Type:** <category>`. Label strings are the canonical role names
  verbatim — `bug`, `enhancement`, `needs-triage`, `needs-info`,
  `ready-for-agent`, `ready-for-human`, `wontfix`.
- **Tracker files are the one exception to "never overwrite"**: change
  `**Status:**`/`**Type:**` in place, and post a comment by appending it under
  a `## Comments` heading. Closing = `**Status:** wontfix` plus the comment.
- **Querying the tracker** = reading those lines across `out/*.md`. A report
  dropped in `in/` can be triaged, but write the tracked copy to `out/`.
- `triage`'s `.out-of-scope/` knowledge base lives at `/work/.out-of-scope/`.
- There are no pull requests here; triage covers issues only.

## When done

Reply with one line per file: the path under `out/`, and one sentence on what is in it. No summaries of the process.
