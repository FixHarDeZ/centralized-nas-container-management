# ink-reader: Fix OPDS Cover Display for KOReader

## Problem

KOReader on Meebook M8 shows only title text in the OPDS catalog — no cover
thumbnails. Root cause in `opds.py`:

1. Cover URLs are relative (`/covers/1.jpg`) — KOReader can't resolve them
2. Relation type is `http://opds-spec.org/image` — KOReader looks for
   `http://opds-spec.org/thumbnail`

## Approach

Three changes:

### 1. Add `INK_BASE_URL` env var

- New config variable in `config.py`, no default (must be set explicitly)
- Used only by OPDS feed builder to construct absolute URLs
- Added to `docker-compose.yml` env section
- Added to `.env` (existing deployment)

### 2. Fix `opds.py` — absolute URLs

Replace relative hrefs with `f"{config.INK_BASE_URL}/covers/{row['id']}.jpg"`
and `f"{config.INK_BASE_URL}/files/{row['id']}.cbz"`.

### 3. Fix `opds.py` — thumbnail relation

Change `rel="http://opds-spec.org/image"` to
`rel="http://opds-spec.org/thumbnail"`.

## Files to change

| File | Change |
|---|---|
| `config.py` | Add `INK_BASE_URL` env var |
| `opds.py` | Use absolute URLs + thumbnail relation |
| `docker-compose.yml` | Add `INK_BASE_URL` to env |
| `ink-reader/.env` | Add `INK_BASE_URL=<NAS_HOST>:5068` |

## Out of scope

- Keep/delete from KOReader (OPDS is read-only by design)
- Streaming CBZ pages (inherent to the format)
- Dashboard redesign for M8 browser

## Verification

1. Deploy to NAS with `INK_BASE_URL` set
2. Add OPDS catalog in KOReader on M8
3. Confirm covers display in the catalog view
4. Confirm CBZ download still works
