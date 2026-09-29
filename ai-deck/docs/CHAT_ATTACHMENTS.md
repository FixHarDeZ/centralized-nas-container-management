# Coding chat attachments

Approved scope: picker, file drop and clipboard-image paste in the selected GitHub coding workspace. Upload before sending; show removable filenames/image previews and progress/error states. Preserve the pending message and attachments when sending fails. Text-only and Documents chat retain their existing behavior.

Files live in the coding volume at `attachments/<owner>/<workspace>/<random-id>/<filename>`, outside Git worktrees. Each upload and submitted reference resolves the authenticated workspace; the client never supplies an absolute path. Filenames are flat, bounded and free of control characters; directory traversal and symlinks are rejected. Stream at most 20 MiB per file, up to 10 attachments per message, publish only complete uploads. Agent prompts carry validated local paths so Claude/Codex can read images or files with their tools. No new provider protocol or external service.

Removing a chip removes it from the pending message, not from disk. Uploaded files remain in the persistent coding volume for conversation references; no automatic Git staging or deletion. Pending attachments remain in the current page only; refreshing clears the pending list. A separate file browser, Documents attachments and retention management are outside this change.

## Implementation plan

- [x] Write failing HTTP tests for upload, workspace ownership, malformed/oversized/incomplete input, duplicate filenames, symlinks, send references and attachment-only turns.
- [x] Add `chat_attachments.py`; integrate PUT and validated send references in `chat.py`; package module and configure nginx upload limits/routing.
- [x] Write failing Chromium checks for picker/drop/paste, queue removal, send gating, retry, workspace URL and responsive layout.
- [x] Add `ui/attachments.js` and composer controls/styles; integrate queue and retry behavior with existing chat lifecycle.
- [x] Run focused tests, full stack suite, syntax and diff checks; review final changes and update README and both stack memory files. Report actual delivery status.
