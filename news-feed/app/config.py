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


def _schedule_file() -> Path:
    return Path(os.getenv("DATA_DIR", "/data")) / "schedule.json"


def _env_defaults() -> dict:
    return {
        "digest_times": [
            t.strip() for t in os.getenv("DIGEST_TIMES", "07:00,12:00,18:00").split(",")
        ],
        "enabled_sources": [
            s.strip()
            for s in os.getenv("ENABLED_SOURCES", ",".join(SOURCES)).split(",")
        ],
        "summarizer_provider": os.getenv("SUMMARIZER_PROVIDER", "anthropic"),
        "summarizer_model": os.getenv("SUMMARIZER_MODEL", "claude-sonnet-4-6"),
        "retention_days": int(os.getenv("RETENTION_DAYS", "30")),
        "summarizer_fallback": [],
        "custom_sources": [],
        "digest_window_buffer_hours": 1.0,
        "digest_size_base": 5,
        "digest_size_max": 10,
        "digest_max_per_source": 2,
    }


def get_all_sources(config: dict) -> dict[str, str]:
    """Return merged dict of built-in SOURCES + custom_sources from config."""
    merged = dict(SOURCES)
    for cs in config.get("custom_sources", []):
        key = cs.get("key", "").strip()
        url = cs.get("url", "").strip()
        if key and url:
            merged[key] = url
    return merged


def get_config() -> dict:
    sf = _schedule_file()
    if sf.exists():
        return json.loads(sf.read_text())
    return _env_defaults()


def update_config(data: dict) -> dict:
    current = get_config()
    current.update(data)
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    _schedule_file().write_text(json.dumps(current, indent=2))
    return current
