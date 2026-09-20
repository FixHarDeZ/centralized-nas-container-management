import sys
from pathlib import Path

# upload.py sits at the stack root, not in a package — the image drops it next
# to ttyd and runs it directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
