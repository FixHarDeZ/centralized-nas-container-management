from apscheduler.schedulers.background import BackgroundScheduler

import config
import db
import scraper
from sqlite_backup import backup_db

_sched = BackgroundScheduler(timezone=config.TZ)


def scrape_job():
    try:
        result = scraper.scrape_cycle()
        print(f"[scrape] {result}", flush=True)
    except Exception as e:  # scrape_cycle already logs; belt & braces
        print(f"[scrape] crashed: {e}", flush=True)
        db.log_scrape(0, 0, str(e))


def expiry_job() -> int:
    count = 0
    for tid in db.expired_ids():
        if db.purge_title(tid):
            count += 1
    print(f"[expiry] purged {count}", flush=True)
    return count


def backup_job():
    backup_db(config.DB_PATH, config.BACKUP_DIR, prefix="ink")


def start():
    _sched.add_job(scrape_job, "interval", hours=config.SCRAPE_INTERVAL_HOURS,
                   id="scrape")
    _sched.add_job(expiry_job, "cron", hour=4, minute=0, id="expiry")
    _sched.add_job(backup_job, "cron", hour=3, minute=0, id="backup")
    _sched.start()


def shutdown():
    if _sched.running:
        _sched.shutdown(wait=False)
