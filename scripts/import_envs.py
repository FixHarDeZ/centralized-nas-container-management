#!/usr/bin/env python3
"""One-shot migration helper: read every current <stack>/.env and the root
.env, build secrets/vault.yaml organized as shared:/stacks:, without echoing
any values to stdout. Intended to run ONCE before encrypting.

Output: secrets/vault.yaml (plaintext). Stdout reports counts only.

Usage:
    python3 scripts/import_envs.py [--root REPO_ROOT] [--output PATH]

Delete this script after Phase A cutover (Task 19).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

# ────────────────────────────────────────────────────────────────────────────
# IMPORT MAP — for every current <stack>/.env key, declare where it lands in
# the vault. Keys that should remain literals (public config) are listed in
# LITERAL_KEYS and skipped from the vault entirely.
# ────────────────────────────────────────────────────────────────────────────

LITERAL_KEYS: set[tuple[str, str]] = {
    # (stack, env_name) tuples that should live in the per-stack manifest as
    # `literals:` (public config) — not in the encrypted vault.
    ("news-feed", "SUMMARIZER_PROVIDER"),
    ("news-feed", "SUMMARIZER_MODEL"),
    ("news-feed", "DIGEST_TIMES"),
    ("news-feed", "ENABLED_SOURCES"),
    ("news-feed", "RETENTION_DAYS"),
    ("news-feed", "DATA_DIR"),
    ("hermes-agent", "HERMES_UID"),
    ("hermes-agent", "HERMES_GID"),
    ("maid-tracker", "MONTHLY_REPORT_TIME"),
    ("secretary/ingest", "QDRANT_URL"),
    ("secretary/ingest", "COLLECTION_NAME"),
    ("secretary/ingest", "STATE_DB"),
    ("secretary/ingest", "NOTION_SOURCE_TYPE"),
    ("secretary/ingest", "NOTION_DATABASE_ID"),
    ("secretary/ingest", "NOTION_ROOT_PAGE_ID"),
    ("secretary/query", "QDRANT_URL"),
    ("secretary/query", "COLLECTION_NAME"),
    ("secretary/query", "LLM_PROVIDER"),
    ("secretary/query", "ANTHROPIC_MODEL"),
    ("secretary/query", "OPENROUTER_MODEL"),
    ("secretary/query", "OPENROUTER_BASE_URL"),
    ("secretary/query", "NOUS_MODEL"),
    ("secretary/query", "NORUS_MODEL"),
    ("secretary/query", "COHERE_RERANK_MODEL"),
    ("uptime-kuma", "NAS_VOLUME_ROOT"),
    ("jellyfin", "NAS_VOLUME_ROOT"),
    ("jellyfin", "NAS_MEDIA_ROOT"),
}

# Per-stack mappings: ENV name → vault dotted path (excluding literals above).
IMPORT_MAP: dict[str, dict[str, str]] = {
    "root": {
        "NAS_USER": "shared.nas.user",
        "NAS_HOST": "shared.nas.host",
        "NAS_PORT": "shared.nas.port",
        "NAS_SSH_KEY": "shared.nas.ssh_key",
        "NAS_TARGET_PATH": "shared.nas.target_path",
        "NAS_SUDO_PASSWORD": "shared.nas.sudo_password",
        # NAS_SSH_ALIAS handled as a literal in deploy.manifest.yaml
        # SYNC_NOTION_TOKEN / NOTION_SUMMARY_DATABASE_ID: sync_notion.py is
        # being deleted; skip these — they were leaked anyway and the user
        # should rotate them outside this migration.
    },
    "homepage": {
        "NAS_VOLUME_ROOT": "stacks.homepage.nas_volume_root",
        "NAS_VOLUME_STORAGE": "stacks.homepage.nas_volume_storage",
        "HOMEPAGE_ALLOWED_HOSTS": "stacks.homepage.allowed_hosts",
        "HOMEPAGE_VAR_DDNS_BASE_HTTP": "stacks.homepage.var_ddns_base_http",
        "HOMEPAGE_VAR_DDNS_BASE_HTTPS": "stacks.homepage.var_ddns_base_https",
        "HOMEPAGE_VAR_QUICKCONNECT_URL": "stacks.homepage.var_quickconnect_url",
        "HOMEPAGE_VAR_NAS_URL": "stacks.homepage.var_nas_url",
        "HOMEPAGE_VAR_NAS_USERNAME": "stacks.homepage.var_nas_username",
        "HOMEPAGE_VAR_NAS_PASSWORD": "stacks.homepage.var_nas_password",
        "HOMEPAGE_VAR_JELLYFIN_URL": "stacks.homepage.var_jellyfin_url",
        "HOMEPAGE_VAR_JELLYFIN_KEY": "stacks.homepage.var_jellyfin_key",
        "HOMEPAGE_VAR_PLEX_URL": "stacks.homepage.var_plex_url",
        "HOMEPAGE_VAR_PLEX_KEY": "stacks.homepage.var_plex_key",
        "HOMEPAGE_VAR_PORTAINER_URL": "stacks.homepage.var_portainer_url",
        "HOMEPAGE_VAR_PORTAINER_KEY": "stacks.homepage.var_portainer_key",
        "HOMEPAGE_VAR_UPTIME_KUMA_URL": "stacks.homepage.var_uptime_kuma_url",
        "HOMEPAGE_VAR_UPTIME_KUMA_SLUG": "stacks.homepage.var_uptime_kuma_slug",
        "HOMEPAGE_VAR_MAID_TRACKER_URL": "stacks.homepage.var_maid_tracker_url",
        "HOMEPAGE_VAR_TORRENTWATCH_URL": "stacks.homepage.var_torrentwatch_url",
        "HOMEPAGE_VAR_NEWS_FEED_HTTP": "stacks.homepage.var_news_feed_http",
        "HOMEPAGE_VAR_NEWS_FEED_HTTPS": "stacks.homepage.var_news_feed_https",
        "HOMEPAGE_VAR_HERMES_HTTP": "stacks.homepage.var_hermes_http",
        "HOMEPAGE_VAR_HERMES_HTTPS": "stacks.homepage.var_hermes_https",
        "HOMEPAGE_VAR_N8N_HTTP": "stacks.homepage.var_n8n_http",
        "HOMEPAGE_VAR_N8N_HTTPS": "stacks.homepage.var_n8n_https",
    },
    "news-feed": {
        # Current news-feed/.env only has OPENROUTER + Telegram + ADMIN.
        # ANTHROPIC + LINE_* are NOT currently used (spec example was aspirational).
        "OPENROUTER_API_KEY": "shared.llm.openrouter_api_key",
        "NEWS_FEED_TELEGRAM_BOT_TOKEN": "stacks.news_feed.telegram.bot_token",
        "TELEGRAM_CHAT_ID": "stacks.news_feed.telegram.chat_id",
        "ADMIN_TOKEN": "stacks.news_feed.admin_token",
    },
    "hermes-agent": {
        "OPENROUTER_API_KEY": "stacks.hermes_agent.openrouter_api_key",
        "XIAOMI_API_KEY": "stacks.hermes_agent.xiaomi.api_key",
        "XIAOMI_BASE_URL": "stacks.hermes_agent.xiaomi.base_url",
        "HERMES_TELEGRAM_BOT_TOKEN": "stacks.hermes_agent.telegram.bot_token",
        "TELEGRAM_ALLOWED_USERS": "stacks.hermes_agent.telegram.allowed_users",
        "DISCORD_BOT_TOKEN": "stacks.hermes_agent.discord.bot_token",
        "DISCORD_ALLOWED_GUILDS": "stacks.hermes_agent.discord.allowed_guilds",
    },
    "watchtower": {
        "WATCHTOWER_LINE_CHANNEL_ACCESS_TOKEN": "stacks.watchtower.line.channel_access_token",
        "WATCHTOWER_LINE_USER_ID": "stacks.watchtower.line.user_id",
        "WATCHTOWER_TELEGRAM_BOT_TOKEN": "stacks.watchtower.telegram.bot_token",
        "TELEGRAM_CHAT_ID": "stacks.watchtower.telegram.chat_id",
    },
    "torrentwatch": {
        "NAS_TORRENT_PATH": "stacks.torrentwatch.torrent_path",
        "TORRENTWATCH_SITE_USERNAME": "stacks.torrentwatch.site.username",
        "TORRENTWATCH_SITE_PASSWORD": "stacks.torrentwatch.site.password",
        "TORRENTWATCH_DEFAULT_URLS": "stacks.torrentwatch.default_urls",
        "NGINX_BASIC_AUTH_USER": "stacks.torrentwatch.nginx_basic_auth.user",
        "NGINX_BASIC_AUTH_PASS": "stacks.torrentwatch.nginx_basic_auth.pass",
        "TORRENTWATCH_LINE_ACCESS_TOKEN": "stacks.torrentwatch.line.access_token",
        "TORRENTWATCH_LINE_USER_ID": "stacks.torrentwatch.line.user_id",
        "TORRENTWATCH_TELEGRAM_BOT_TOKEN": "stacks.torrentwatch.telegram.bot_token",
        "TORRENTWATCH_TELEGRAM_CHAT_ID": "stacks.torrentwatch.telegram.chat_id",
    },
    "maid-tracker": {
        "MAID_LINE_CHANNEL_ACCESS_TOKEN": "stacks.maid_tracker.line.channel_access_token",
        "MAID_LINE_CHANNEL_SECRET": "stacks.maid_tracker.line.channel_secret",
        "MAID_LINE_GROUP_ID": "stacks.maid_tracker.line.group_id",
        "NGINX_BASIC_AUTH_USER": "stacks.maid_tracker.nginx_basic_auth.user",
        "NGINX_BASIC_AUTH_PASS": "stacks.maid_tracker.nginx_basic_auth.pass",
    },
    "secretary": {
        "N8N_BASIC_AUTH_USER": "stacks.secretary.n8n.basic_auth_user",
        "N8N_BASIC_AUTH_PASSWORD": "stacks.secretary.n8n.basic_auth_password",
        "N8N_WEBHOOK_URL": "stacks.secretary.n8n.webhook_url",
    },
    "secretary/ingest": {
        "SECRETARY_NOTION_TOKEN": "shared.notion.secretary_token",
    },
    "secretary/query": {
        "ANTHROPIC_API_KEY": "stacks.secretary.query.anthropic_api_key",
        "OPENROUTER_API_KEY": "stacks.secretary.query.openrouter_api_key",
        "NORUS_API_KEY": "stacks.secretary.query.norus_api_key",
        "NORUS_BASE_URL": "stacks.secretary.query.norus_base_url",
        "COHERE_API_KEY": "shared.llm.cohere_api_key",
    },
}


def parse_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Strips surrounding quotes."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def deep_set(d: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Set d[a][b][c] = value for path 'a.b.c', creating dicts as needed."""
    parts = dotted_path.split(".")
    cur: dict[str, Any] = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
        if not isinstance(cur, dict):
            raise ValueError(f"path {dotted_path} collides with existing scalar")
    cur[parts[-1]] = value


def import_stack(
    stack_name: str,
    env_file: Path,
    vault: dict[str, Any],
    counters: dict[str, int],
) -> list[str]:
    """Read one .env, push into vault dict, return list of skipped (literal) keys."""
    parsed = parse_env(env_file)
    mapping = IMPORT_MAP.get(stack_name, {})
    skipped: list[str] = []
    for env_key, value in parsed.items():
        if (stack_name, env_key) in LITERAL_KEYS:
            skipped.append(env_key)
            continue
        if env_key not in mapping:
            counters["unmapped"] = counters.get("unmapped", 0) + 1
            print(f"  WARN: no mapping for {stack_name}/{env_key}", file=sys.stderr)
            continue
        deep_set(vault, mapping[env_key], value)
        counters["imported"] = counters.get("imported", 0) + 1
    return skipped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".", type=Path)
    p.add_argument("--output", default=None, type=Path)
    args = p.parse_args(argv)

    root: Path = args.root.resolve()
    output: Path = args.output or root / "secrets" / "vault.yaml"
    output.parent.mkdir(parents=True, exist_ok=True)

    vault: dict[str, Any] = {}
    counters: dict[str, int] = {}

    # root .env first
    skipped = import_stack("root", root / ".env", vault, counters)
    print(
        f"  root: imported {len(IMPORT_MAP['root'])} keys, "
        f"skipped (literal): {skipped or 'none'}",
    )

    # Per-stack
    for stack_name in IMPORT_MAP:
        if stack_name == "root":
            continue
        env_file = root / stack_name / ".env"
        skipped = import_stack(stack_name, env_file, vault, counters)
        n_mapped = len(IMPORT_MAP[stack_name])
        print(
            f"  {stack_name}: imported up to {n_mapped} keys, "
            f"skipped (literal): {skipped or 'none'}",
        )

    # Hard-coded constant fields that aren't sourced from .env files
    deep_set(vault, "shared.nas.target_path", "/volume2/docker")
    deep_set(vault, "shared.nas.ssh_key", "~/.ssh/id_ed25519")
    deep_set(vault, "shared.nas.port", "2222")
    deep_set(vault, "stacks.uptime_kuma.nas_volume_root", "/volume2")
    deep_set(vault, "stacks.jellyfin.nas_volume_root", "/volume2")
    deep_set(vault, "stacks.jellyfin.nas_media_root", "/volume1")

    yaml_text = yaml.safe_dump(vault, default_flow_style=False, sort_keys=True)
    output.write_text(yaml_text)

    print()
    print(f"Wrote {output} ({output.stat().st_size} bytes)")
    print(f"Total imported: {counters.get('imported', 0)} secret keys")
    print(f"Total unmapped (warnings): {counters.get('unmapped', 0)}")
    print()
    print("NEXT: review the file with `sops secrets/vault.yaml` (DO NOT commit),")
    print("then encrypt with: sops -e secrets/vault.yaml > secrets/vault.sops.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
