# Present so pytest puts the stack's scripts/ on sys.path and `import shopee_probe`
# works when the suite is run from the repo root as well as from here.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
