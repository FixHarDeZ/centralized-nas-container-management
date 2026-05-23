import json
import os
from pathlib import Path

SOURCES: dict[str, str] = {
    "techcrunch_ai": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "venturebeat": "https://venturebeat.com/feed/",
    "theverge": "https://www.theverge.com/rss/index.xml",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "gsmarena": "https://www.gsmarena.com/rss-news-reviews.php3",
    "9to5mac": "https://9to5mac.com/feed/",
    "android_authority": "https://www.androidauthority.com/feed/",
}

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = str(DATA_DIR / "news.db")
_SCHEDULE_FILE = DATA_DIR / "schedule.json"


def _env_defaults() -> dict:
    return {
        "digest_times": [t.strip() for t in os.getenv("DIGEST_TIMES", "07:00,12:00,18:00").split(",")],
        "enabled_sources": [s.strip() for s in os.getenv("ENABLED_SOURCES", ",".join(SOURCES)).split(",")],
        "summarizer_provider": os.getenv("SUMMARIZER_PROVIDER", "anthropic"),
        "summarizer_model": os.getenv("SUMMARIZER_MODEL", "claude-sonnet-4-6"),
    }


def get_config() -> dict:
    if _SCHEDULE_FILE.exists():
        return json.loads(_SCHEDULE_FILE.read_text())
    return _env_defaults()


def update_config(data: dict) -> dict:
    current = get_config()
    current.update(data)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _SCHEDULE_FILE.write_text(json.dumps(current, indent=2))
    return current
