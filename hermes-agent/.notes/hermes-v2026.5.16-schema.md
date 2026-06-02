# hermes v2026.5.16 — config schema verification

**Verified:** 2026-06-02
**Method:** Read `/opt/hermes/gateway/config.py` (1874 lines) + `/opt/hermes/hermes_cli/config.py` `DEFAULT_CONFIG` block on running container

## Key revelation: the spec's key names were wrong

The repo `config.yaml.example` and `.notes/00_INDEX.md` documented `session.reset_on_idle_minutes: 60`. **This key has never been honored.** Hermes v2026.5.16 uses `session_reset.idle_minutes` (different namespace) with default `1440` (24 hours) — meaning live sessions have effectively never been idle-reset.

This alone is a major contributor to mimo cache miss: sessions persisting 24 hours accumulate context that drifts the prefix between every request.

## Tier 1 — verified, applies (CORRECTED key names)

| Spec said | Real key | Source | Notes |
|---|---|---|---|
| `session.reset_on_idle_minutes` | `session_reset.idle_minutes` | `gateway/config.py:712-714, 237-277` | Default 1440 (24h). Mapped via `yaml_cfg.get("session_reset")` → `SessionResetPolicy.from_dict`. |
| (implied) | `session_reset.mode` | `gateway/config.py:248` | Values: `"daily"`, `"idle"`, `"both"`, `"none"`. Default `"both"`. For our tune we want `"both"` or `"idle"`. |

## Tier 2 — verified, applies (DIFFERENT keys than spec)

| Spec said | Real key | Source | Default | Notes |
|---|---|---|---|---|
| `session.max_iterations` / `agent.max_iterations` | `agent.max_turns` | `hermes_cli/config.py:478` | **90** | Cap on conversation turns. Live session log "iteration 13/60" suggests live override; we'll set explicit 20. |
| `memory.enabled` | `memory.memory_enabled` | `hermes_cli/config.py:1129` | **True** | Bounded curated memory **injected into system prompt** — primary cache-miss driver. |
| (not in spec) | `memory.user_profile_enabled` | `hermes_cli/config.py:1130` | **True** | User profile injected into system prompt alongside memory. Same cache-killer mechanism. |
| (not in spec) | `memory.memory_char_limit` | `hermes_cli/config.py:1131` | 2200 (~800 tok) | Size of memory block. |
| (not in spec) | `memory.user_char_limit` | `hermes_cli/config.py:1132` | 1375 (~500 tok) | Size of user profile block. |

## Tier 3 — verified, optionally applies

| Real key | Source | Default | Notes |
|---|---|---|---|
| `compression.enabled` | `hermes_cli/config.py:763` | True | Lossy context compression. Triggers prefix rewrite → cache miss. |
| `compression.threshold` | `hermes_cli/config.py:764` | **0.50** | Compress at 50% context use. Raising to 0.80 delays compression → prefix stable longer. |
| `compression.protect_first_n` | `hermes_cli/config.py:768` | 3 | Non-system head messages preserved verbatim. |
| `agent.image_input_mode` | `hermes_cli/config.py:555` | `"auto"` | `"text"` = pre-analyze images via vision_analyze tool and prepend description as text. Main model never sees pixels. Big saver if user sends screenshots regularly. |
| `tool_output.max_bytes` | `hermes_cli/config.py:739` | 50_000 | Terminal output cap. Lower → less garbage in context. |
| `file_read_max_chars` | `hermes_cli/config.py:722` | 100_000 | read_file cap. Lower → forces pagination, smaller turns. |
| `agent.api_max_retries` | `hermes_cli/config.py:502` | 3 | App-level retry on API errors. Lowering to 1 = faster failover. |
| `agent.gateway_timeout` | `hermes_cli/config.py:483` | 1800 (30 min) | Inactivity timeout for gateway runs. |
| `tool_loop_guardrails.hard_stop_enabled` | `hermes_cli/config.py:749` | False | Opt-in hard stop after N repeated failures. Worth enabling. |

## Tier 3 — verified, NOT in v2026.5.16

| Spec speculated | Status | Notes |
|---|---|---|
| `tools` whitelist | Absent | No top-level tool whitelist. `agent.disabled_toolsets` exists but disables whole toolsets, not individual tools. |
| `vision.max_images_per_session` | Absent | Per-session image cap is not configurable. Use `agent.image_input_mode: "text"` instead. |
| `auto_compact` | Absent (named differently) | Same concept lives as `compression.enabled` / `compression.threshold`. |
| `model.max_tokens` | Absent in DEFAULT_CONFIG | Provider-level max_tokens not surfaced in hermes config. mimo's own defaults govern. |

## Notable extras discovered (not used by our tune, but worth knowing)

| Real key | Source | Default | Notes |
|---|---|---|---|
| `prompt_caching.cache_ttl` | `hermes_cli/config.py:779` | `"5m"` | Anthropic prompt caching TTL. Not applicable to mimo. |
| `openrouter.response_cache` | `hermes_cli/config.py:798` | True | OpenRouter response-cache for identical requests. Already on; doesn't help conversation-prefix caching but ok. |
| `agent.api_max_retries` | `hermes_cli/config.py:502` | 3 | See Tier 3. |
| `agent.gateway_notify_interval` | `hermes_cli/config.py:527` | 180 | Status-message interval (the "Still working..." messages). |
| `auxiliary.compression.provider` etc. | `hermes_cli/config.py:867-874` | "auto" | Aux model used to summarize during compression. Could route to cheaper model. |
| `delegation.max_iterations` | `hermes_cli/config.py:1159` | 50 | Subagent iteration cap (NOT the main agent's — that's `agent.max_turns`). |

## Final decision — keys to apply

### Gateway block (top-level `session_reset:`)

```yaml
session_reset:
  mode: both           # daily boundary OR idle timeout, whichever first
  idle_minutes: 15     # was effectively 1440 (24h default, never overridden)
  at_hour: 4           # 4am daily reset (default, kept explicit for clarity)
```

### Agent / memory / compression (under `agent:` / `memory:` / `compression:` blocks)

```yaml
agent:
  max_turns: 20            # was 90 default / 60 in live runs — cap iteration runaway
  api_max_retries: 1       # was 3 — faster failover on flaky mimo calls
  image_input_mode: text   # was "auto" — kill vision tokens (uncacheable) when user sends screenshots

memory:
  memory_enabled: false        # was True — PRIMARY cache-miss fix (no mutable memory in system prompt)
  user_profile_enabled: false  # was True — same mechanism, second injection block

compression:
  threshold: 0.80          # was 0.50 — delay compression rewrite; cache stays valid longer
```

### Skip / leave alone

- `compression.enabled` — leave True. Disabling risks OOM at provider boundary on long sessions. Raising the threshold gives most of the benefit without that risk.
- `tool_output.max_bytes`, `file_read_max_chars` — leave default. Not the bottleneck for token bleed on this workload.
- `agent.gateway_timeout` — leave default 1800s. session_reset.idle_minutes already covers the case we care about.
- `tool_loop_guardrails.hard_stop_enabled` — defer. max_turns hard cap covers it.
- Anthropic / OpenRouter cache settings — not applicable to mimo conversation-prefix caching.

## Implications for the design spec

The original spec's success criterion (cache hit ≥ 50% sustained, daily tokens ≤ 15M) is **more achievable than the spec assumed**, because:
- `memory.memory_enabled: false` directly removes the most likely cache-miss driver
- `session_reset.idle_minutes` going from 1440→15 ends the 24-hour zombie-session scenario
- `image_input_mode: text` eliminates vision-token spend entirely

Risk: turning off memory means hermes loses persistent user preferences across sessions. One-week trial as planned; revisit at +72h verification.
