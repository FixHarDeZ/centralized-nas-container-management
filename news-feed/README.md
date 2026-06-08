# news-feed

AI & IT news feed bot with Thai summaries. Fetches RSS from 7 sources, summarises via Claude or DeepSeek (OpenRouter), sends digest to LINE + Telegram, serves a dashboard at port 5064 behind an Nginx basic-auth sidecar.

## Setup

1. Copy and fill env:
   ```bash
   cp .env.example .env
   ```

2. Fill in `.env`: at minimum `ANTHROPIC_API_KEY` (or `OPENROUTER_API_KEY` + set `SUMMARIZER_PROVIDER=openrouter`), `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

3. Create `nginx/.htpasswd` locally (gitignored) with the provisioned basic-auth credentials before deploy.

4. Deploy:
   ```bash
   scripts/deploy.sh -s news-feed
   ```

## Dashboard

`http://<NAS_HOST>:5064` — Nginx basic auth in front of the dashboard and API. After login, you can access Source Health, News Timeline, AI Price Tracker, Leaderboard, Digest History, Schedule Config.

## Switch LLM Model

Via dashboard → Schedule Config → set Provider + Model → Save.
Or via API:
```bash
curl -u <BASIC_AUTH_USER>:<BASIC_AUTH_PASSWORD> -X POST http://<NAS_HOST>:5064/api/schedule \
  -H 'Content-Type: application/json' \
  -d '{"summarizer_provider":"openrouter","summarizer_model":"deepseek/deepseek-chat"}'
```

## Manual Digest Trigger

```bash
curl -u <BASIC_AUTH_USER>:<BASIC_AUTH_PASSWORD> -X POST http://<NAS_HOST>:5064/api/digest/trigger \
  -H "X-Admin-Token: <ADMIN_TOKEN>"
```

### Digest Tuning (schedule.json / dashboard)

Adaptive lookback + dynamic size replaces the old fixed 12h/5-article model.

| Key                          | Default | Range   | Purpose |
|------------------------------|---------|---------|---------|
| `digest_window_buffer_hours` | `1.0`   | 0–6     | Added to the gap between consecutive digest ticks; clamped to [4, 36] |
| `digest_size_base`           | `5`     | 1–20    | Base articles per digest |
| `digest_size_max`            | `10`    | 1–20    | Hard ceiling (must be ≥ base) |
| `digest_max_per_source`      | `2`     | 1–5     | Per-source diversity cap |

Window is computed at each tick as `(now - prev_tick) + buffer`, so the overnight
07:00 digest sees ~14h while the 12:00 digest sees ~6h. Articles never fall off
between fetch and the next eligible digest under normal cadence.
