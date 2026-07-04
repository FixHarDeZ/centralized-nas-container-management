from __future__ import annotations

import sqlite3

import yaml

from app import db


def seed_from_config_if_empty(conn: sqlite3.Connection, config_path: str) -> None:
    """Seed monitored_containers from config.yaml, but only on first boot
    (table empty). After that, all changes go through the dashboard/API —
    config.yaml is never read again or written back to."""
    if db.list_monitored_containers(conn):
        return
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    for name, entry in (cfg.get("containers") or {}).items():
        db.upsert_monitored_container(
            conn,
            name,
            entry.get("repo"),
            entry.get("subdir"),
            entry.get("maturity", "dev"),
            1 if entry.get("notify_only") else 0,
            0,
            entry.get("regex_override"),
        )
