# n8n Global Error Workflow — Design Spec

**Date:** 2026-06-05
**Stack:** `secretary/`
**Status:** Approved

## Goal

Send Telegram alert whenever any n8n workflow fails. Alert must cover all existing and future workflows without per-workflow configuration.

## Approach

Use n8n's built-in **Error Workflow** feature. n8n automatically invokes a designated "Error Workflow" whenever any other workflow fails. No polling, no per-workflow changes needed.

## Workflow Design

**Name:** `Secretary_Error_Alerter`

### Nodes

| Node | Type | Purpose |
|---|---|---|
| Error Trigger | `n8n-nodes-base.errorTrigger` | Receives error context from n8n automatically |
| Set Message | Set | Formats error info into Telegram message string |
| Send Alert | `n8n-nodes-base.telegram` | Sends message to Telegram chat |

### Message Template

```
🔴 Workflow Failed

Workflow: {{ $workflow.name }}
Execution ID: {{ $execution.id }}
Error: {{ $json.execution.error.message }}
Time: {{ $now.toISO() }}
```

### Telegram Config

- **chat_id:** `8663614341`
- **Credential:** same Telegram credential used by `Secretary_Bot` workflow

## Data Flow

```
[any workflow fails]
        ↓ (n8n internal, automatic)
[Error Trigger]
        ↓
[Set Message]  — formats $workflow.name, $execution.id, error.message, $now
        ↓
[Telegram: Send Alert]  — chat_id 8663614341
```

## Activation Steps

After importing the workflow JSON into n8n:

1. n8n UI → **Settings** → **Workflow Settings** → **Error Workflow** → select `Secretary_Error_Alerter`
2. Toggle workflow **Active** (ON)

## Scope & Constraints

- Covers all existing workflows: `Secretary_Auto_Sync`, `Secretary_Bot`
- Covers all future workflows automatically (global setting)
- n8n prevents recursive loops — this workflow's own failures do NOT re-trigger itself
- Workflow JSON saved to `secretary/n8n-workflows/` and git-tracked (consistent with existing backup pattern)
- No new env vars or secrets needed

## Out of Scope

- Per-workflow silencing / suppression rules
- Alert deduplication / cooldown
- Retry-on-fail logic
