# Secretary Query — Nous Portal OAuth Integration

**Date:** 2026-05-28  
**Stack:** `secretary/query`  
**Scope:** Remove `norus` provider, replace with `nous` provider using OAuth 2.0 Device Code flow

---

## 1. Context

The `secretary/query` service currently supports three LLM providers: `anthropic`, `openrouter`, and `norus`. The `norus` provider used a static API key against `https://api.norus.ai/v1`. This provider is being removed and replaced with **Nous Portal** (`nousresearch.com`), which exposes an OpenAI-compatible inference API at `https://inference-api.nousresearch.com/v1` and authenticates via **OAuth 2.0 Device Authorization Grant** (RFC 8628).

---

## 2. OAuth Device Code Flow

Nous Portal does not use Authorization Code (browser redirect). Instead it uses **Device Code flow**:

1. App POSTs to `https://portal.nousresearch.com/api/oauth/device/code` with `client_id=hermes-cli`
2. Portal returns `{device_code, user_code, verification_uri, expires_in, interval}`
3. User opens `verification_uri` in browser, enters `user_code`, approves
4. App polls token endpoint until approval or expiry → receives `{access_token, refresh_token, expires_in}`
5. App stores tokens in `/data/nous_token.json`
6. Before each LLM call, app checks token expiry; if expired, calls refresh endpoint automatically

**OAuth endpoints (from NousResearch/hermes-agent source):**
- Device code: `POST https://portal.nousresearch.com/api/oauth/device/code`
- Token: `POST https://portal.nousresearch.com/api/oauth/token`
- Client ID: `hermes-cli`
- Scopes: `inference:invoke`

**Inference base URL:** `https://inference-api.nousresearch.com/v1`

---

## 3. New Module: `nous_auth.py`

A singleton `NousTokenManager` class handles the entire token lifecycle.

```
NousTokenManager
├── start_device_flow()   → POST device/code, return {verification_uri, user_code, expires_in}
│                           starts background asyncio.Task polling every `interval` seconds
├── poll_for_token()      → background loop: POST token endpoint, on success saves tokens + stops
├── get_access_token()    → returns valid access_token (refreshes if < 60s to expiry)
├── _refresh()            → POST token endpoint with refresh_token → update stored tokens
└── _load() / _save()     → read/write /data/nous_token.json atomically
```

**Token file** (`/data/nous_token.json`):
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "expires_at": 1748000000
}
```

File written atomically (write to `.tmp`, then `os.replace`) to avoid corruption.

---

## 4. LLM Client Changes (`llm_client.py`)

Remove the `norus` block entirely. Add a `nous` block:

```python
if _PROVIDER == "nous":
    token = await nous_auth.token_manager.get_access_token()
    client = AsyncOpenAI(
        base_url="https://inference-api.nousresearch.com/v1",
        api_key=token,          # Bearer token used as api_key
    )
    model = os.getenv("NOUS_MODEL", "Hermes-4-70B")
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    if not resp.choices:
        raise RuntimeError("Nous returned no choices")
    return resp.choices[0].message.content or ""
```

The `AsyncOpenAI` client singleton for `nous` is separate from `openrouter` (different base URLs). The `_openai_client` global is replaced with two: `_openrouter_client` and `_nous_client`.

---

## 5. FastAPI Endpoint Changes (`main.py`)

**Remove:** `norus` from `_active_model_name()` mapping.

**Add:**
```
GET /nous/auth       → start device flow, return {verification_uri, user_code, expires_in, message}
GET /nous/auth/status → return {authenticated: bool, expires_at: str|null}
```

`/nous/auth` is idempotent — if a valid token already exists it returns `{authenticated: true}` without starting a new flow.

---

## 6. `.env.example` Changes

**Remove:**
```
NORUS_API_KEY=xxx
NORUS_MODEL=xxx
NORUS_BASE_URL=https://api.norus.ai/v1
```

**Add:**
```
# Nous Portal (OAuth Device Code — run GET /nous/auth once after deploy)
NOUS_MODEL=Hermes-4-70B
```

`LLM_PROVIDER=nous` is the value to set when using this provider (alongside existing `anthropic`, `openrouter` options).

---

## 7. Test Plan

| Test file | What to test |
|-----------|-------------|
| `test_llm_client.py` | Delete `test_norus_returns_text`. Add `test_nous_returns_text`: mock `nous_auth.token_manager.get_access_token`, mock `_nous_client`, verify correct model + messages |
| `test_nous_auth.py` (new) | `test_start_device_flow_returns_expected_fields`: mock httpx POST → verify return shape. `test_get_access_token_refreshes_when_expired`: set `expires_at` to past → verify `_refresh()` called. `test_save_load_roundtrip`: write then read token file → data matches |

Tests mock all HTTP calls (no real network). `nous_auth` uses `httpx.AsyncClient` directly (not openai SDK) for OAuth endpoints.

---

## 8. Error Handling

| Scenario | Behaviour |
|----------|-----------|
| `/nous/auth` called but poll times out (user didn't approve) | background task stops, next `/nous/auth` call starts fresh flow |
| `get_access_token()` called before any token exists | raises `RuntimeError("Nous not authenticated — call GET /nous/auth first")` → 502 from query endpoint |
| Refresh token expired | same RuntimeError, user must re-run `/nous/auth` |
| Nous API returns no choices | raises `RuntimeError("Nous returned no choices")` |

---

## 9. Setup Instructions (Post-Deploy)

```bash
# 1. Set LLM_PROVIDER=nous and NOUS_MODEL in secretary/query/.env
# 2. Deploy to NAS
# 3. One-time auth:
curl http://<NAS_HOST>:5065/nous/auth
# → returns {verification_uri, user_code}
# 4. Open verification_uri in browser, enter user_code, approve
# 5. Container auto-receives token and stores it in /data/nous_token.json
# 6. Verify: curl http://<NAS_HOST>:5065/nous/auth/status
# → {authenticated: true, expires_at: "..."}
```
