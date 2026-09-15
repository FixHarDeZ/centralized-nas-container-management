# claude-desk work folder

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

## When done

Reply with one line per file: the path under `out/`, and one sentence on what is in it. No summaries of the process.
