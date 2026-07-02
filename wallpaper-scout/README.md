# Wallpaper Scout

Research + curate wallpapers from multiple sources into Synology Photos, split by purpose (mobile/pc) and topic.

## Sources

Each topic selects one or more sources (multi-select on the dashboard). Adding sources widens the pool so the same images stop repeating.

| Source | Best for | Notes |
|---|---|---|
| `wallhaven` | Real people / idols, photographic | Default. Server-side ratio+resolution filter. |
| `booru` | Anime / game characters | yande.re + konachan.net (Moebooru). `rating:s` only. Client-side aspect+res filter (pc floor 1920×1080, mobile 1080×1920). konachan.**net** used — konachan.com is Cloudflare-walled; a browser User-Agent is sent. yande.re skews portrait/mobile, konachan skews landscape/pc — complementary. |
| `reddit` | *(deferred)* Idol fan photos | Reddit killed its unauth JSON API (403 everywhere). Needs OAuth (script app + client_id/secret in vault). Not built yet. |

`rating:s` on booru is SFW-legal but still surfaces suggestive tags (bikini/cleavage) — add a tag blacklist later if it matters.

## How it works

1. Add a "topic" (a search term like `IU` or `Wuthering Waves`) via the dashboard, choosing which purpose(s), which source(s), and how many times/day to scrape.
2. On first run for a topic, an LLM (MiMo primary, Anthropic fallback) expands the topic into a few alias search terms (romanization, alt names) to widen recall.
3. Each scheduled cycle searches every selected source for that topic+purpose and downloads up to `max_new_per_cycle` images it hasn't downloaded before. `max_new_per_cycle` is a shared per-purpose cap filled in source list order (wallhaven first, then booru). Dedup key = source-namespaced image id (`wh` bare, `yr:`/`kc:` for booru) so ids can't collide across sources.
4. Images land in `/photos_root/<purpose>/<topic-slug>/<image-id>.<ext>` (`:` in namespaced ids becomes `-` in filenames), bind-mounted to `/volume1/homes/fixhardez/Photos/wallpapers/...` on the NAS — Synology Photos auto-indexes this under its "Folders" tab (not "Albums" — no DSM API/login used anywhere in this stack).
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
