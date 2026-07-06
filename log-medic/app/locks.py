from __future__ import annotations

import threading

# ponytail: one global lock over the single shared workspace clone. Serializes
# run_fix (branch cut + Claude edits + commit) against deploy (reset --hard + copy).
# Coarse (run_fix can hold it for the full Claude edit window) but correct; the two
# ops are infrequent. Per-repo locks only if multiple clones are ever introduced.
workspace_lock = threading.Lock()
