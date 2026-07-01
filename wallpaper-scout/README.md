# Wallpaper Scout

Research + curate wallpapers from Wallhaven into Synology Photos, split by purpose (mobile/pc) and topic.

## How it works

1. Add a "topic" (a search term like `IU` or `Wuthering Waves`) via the dashboard, choosing which purpose(s) apply and how many times/day to scrape.
2. On first run for a topic, an LLM (MiMo primary, Anthropic fallback) expands the topic into a few alias search terms (romanization, alt names) to widen Wallhaven recall.
3. Each scheduled cycle searches Wallhaven (SFW only) for that topic+purpose, using a hardcoded ratio/resolution preset per purpose, and downloads up to `max_new_per_cycle` images it hasn't downloaded before (Wallhaven's own image ID is the dedup key).
4. Images land in `/photos_root/<purpose>/<topic-slug>/<wallhaven-id>.<ext>`, bind-mounted to `/volume1/homes/fixhardez/Photos/wallpapers/...` on the NAS — Synology Photos auto-indexes this under its "Folders" tab (not "Albums" — no DSM API/login used anywhere in this stack).
5. Once/day, a Telegram message (same bot/chat as `news-feed`) summarizes how many new images were downloaded, broken down by topic.

## Known limitations (v1)

- Celebrity/idol topics are best-effort: Wallhaven's `people` category skews model/cosplay and idol tagging is thin, so a niche celebrity topic may return few or no results under the SFW+resolution filters.
- No perceptual-hash dedup — only exact Wallhaven-ID dedup. A different upload of visually-identical art won't be caught.
- No auto-delete/retention — downloaded images are kept forever; storage is bounded only by how many topics are enabled and their frequency/per-cycle-cap settings.

## Ports

| Context | Port |
|---|---|
| Container internal | 8000 |
| NAS host (LAN, via nginx basic auth) | 5067 |

## Deploy checklist

See `docs/superpowers/plans/2026-07-01-wallpaper-scout-stack.md` Task 8 for the one-time NAS setup (fixhardez UID/GID lookup, wallpapers directory pre-creation, `nginx/.htpasswd`).
