# Observed 'unusual activity' Failed cards (2026-11-09, shelf clip run)

Facts from one run; the cause is still unconfirmed.

- Chrome launched headful on Xvfb :99 (flags per flow-browser-env.md). The User-Agent was plain `Chrome/145` (not HeadlessChrome), so the headless-UA theory did not explain this failure.
- First Start generation (4 s, presenter shot, product + character chips) returned a `Failed` card: "We noticed some unusual activity...". No credits were charged.
- Retry about 7 minutes later, with the same chip and prompt setup, failed the same way.
- A `Failed` card keeps its text on the page after the prompt box clears, so a text check for 'unusual activity' can match an old card. Compare card counts before and after a submit.
- Deciding next step: this matches the 'pace submits' section. Stop after one retry and report, rather than retrying in a loop.
- Candidate fixes Fix may choose, none verified here: close Chrome with CDP Browser.close and relaunch; clear flow.google.com and accounts.google.com site data and re-login manually (YouTube UrTutor, 2026-05-23, describes this for an Ultra account, not PRO; it needs a human login).

## Picker and upload recipe that worked on the narrow-check desktop layout (1280 px)
- Open the picker with `button[aria-label="Add ingredients to the prompt box"]`.
- The 'Upload media' control is a SPAN with text `Upload media` in the picker, not a button with aria-label. Click it by text.
- After that, `DOM.getDocument(pierce=True)` → `input[type=file]` returned nodeId 0 when clicked from the sidebar 'Upload' item, but found the file input when clicked from the picker's Upload media span.
- Desktop popover: select a row, then click `button` with text `Add to prompt` at the preview pane. One selected row = one chip.
- The picker search box clears with Ctrl+A then Backspace via CDP key events. Plain Backspace did not clear it.
- Searching `ref2` returned no rows after the first upload, although ref2.jpg was listed in the page text. The second upload may not have landed. Verify each reference by its chip alt text, and check the Uploads list before relying on a second reference.
