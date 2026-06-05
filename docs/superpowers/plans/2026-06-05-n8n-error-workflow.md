# n8n Global Error Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create an n8n workflow that sends a Telegram alert whenever any workflow in the secretary stack fails.

**Architecture:** A single n8n workflow (`Secretary_Error_Alerter`) uses an Error Trigger node — n8n's built-in mechanism that fires automatically when any other workflow fails. The trigger feeds into a Telegram node that sends a formatted alert to chat_id `8663614341`. After import, the workflow must be activated and set as the global error workflow in n8n Settings.

**Tech Stack:** n8n (Error Trigger node), Telegram API (existing "Secretary Bot" credential `QiUZ8rINLwwPL1qu`), `scripts/n8n_import.sh` for deployment.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `secretary/n8n-workflows/Secretary_Error_Alerter.json` | Create | Workflow JSON — Error Trigger → Telegram alert |

No other files need modification.

---

### Task 1: Create workflow JSON

**Files:**
- Create: `secretary/n8n-workflows/Secretary_Error_Alerter.json`

- [ ] **Step 1: Write the workflow JSON**

Create `secretary/n8n-workflows/Secretary_Error_Alerter.json` with this exact content:

```json
{
  "name": "Secretary Error Alerter",
  "active": false,
  "nodes": [
    {
      "parameters": {},
      "type": "n8n-nodes-base.errorTrigger",
      "typeVersion": 1,
      "position": [0, 0],
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "name": "Error Trigger"
    },
    {
      "parameters": {
        "chatId": "8663614341",
        "text": "=🔴 Workflow Failed\n\nWorkflow: {{ $json.workflow.name }}\nExecution ID: {{ $json.execution.id }}\nError: {{ $json.execution.error.message }}\nLast Node: {{ $json.execution.lastNodeExecuted }}\nTime: {{ $now.toISO() }}",
        "additionalFields": {}
      },
      "type": "n8n-nodes-base.telegram",
      "typeVersion": 1.2,
      "position": [240, 0],
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "name": "Send Alert",
      "credentials": {
        "telegramApi": {
          "id": "QiUZ8rINLwwPL1qu",
          "name": "Secretary Bot"
        }
      }
    }
  ],
  "connections": {
    "Error Trigger": {
      "main": [
        [
          {
            "node": "Send Alert",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  },
  "settings": {
    "executionOrder": "v1"
  },
  "meta": {
    "templateCredsSetupCompleted": true
  },
  "pinData": {}
}
```

- [ ] **Step 2: Verify JSON is valid**

```bash
python3 -c "import json; d=json.load(open('secretary/n8n-workflows/Secretary_Error_Alerter.json')); print('OK:', d['name'], '|', len(d['nodes']), 'nodes')"
```

Expected output:
```
OK: Secretary Error Alerter | 2 nodes
```

- [ ] **Step 3: Commit**

```bash
git add secretary/n8n-workflows/Secretary_Error_Alerter.json
git commit -m "feat(secretary): add n8n global error alerter workflow"
```

---

### Task 2: Import workflow to n8n on NAS

**Files:**
- Run: `scripts/n8n_import.sh`

- [ ] **Step 1: Ensure secrets are available**

```bash
ls secretary/.env
```

Expected: file exists (needs `N8N_API_KEY`). If missing, run `make secrets` first.

- [ ] **Step 2: Import the workflow**

```bash
./scripts/n8n_import.sh secretary/n8n-workflows/Secretary_Error_Alerter.json
```

Expected output ends with:
```
✔ Created: Secretary_Error_Alerter.json
✔ Import complete: 1 created, 0 updated
```

If it says `Updated` instead of `Created`, that is also fine — means a previous import existed.

---

### Task 3: Activate workflow and configure as global error handler

This task is done in the n8n browser UI. n8n is accessible at the HTTPS proxy URL (see `.env.deploy` for `NAS_HOST`): `https://<NAS_HOST>:15678` or via direct HTTP `http://<NAS_HOST>:5678` on the internal network.

- [ ] **Step 1: Open n8n and activate the workflow**

1. Open n8n UI in browser
2. Find `Secretary Error Alerter` in the workflow list
3. Click into it
4. Toggle the **Active** switch to ON (top-right of the workflow editor)
5. Confirm it shows green/active

- [ ] **Step 2: Set as global error workflow**

1. In n8n UI, click **Settings** (gear icon, left sidebar or top menu)
2. Navigate to **General** (or **Workflow Settings**)
3. Find **Error Workflow** dropdown
4. Select `Secretary Error Alerter`
5. Save

> **Note:** In n8n, the "Error Workflow" setting location depends on version. In newer n8n (≥1.x), this setting is found under **Settings → General → Error Workflow**. If you cannot find it globally, the alternative is to set `settings.errorWorkflow` per-workflow (see Task 4 fallback below).

---

### Task 4: Test the alert

- [ ] **Step 1: Create a test workflow that always fails**

In n8n UI:
1. Click **+ New Workflow**
2. Add a **Manual Trigger** node
3. Add a **Code** node connected to the trigger with this code:
   ```javascript
   throw new Error("Test error for alert verification");
   ```
4. Name it `_Test Error` (the underscore helps sort it)
5. Save and click **Execute** (do NOT activate it)

- [ ] **Step 2: Verify Telegram alert arrives**

Check Telegram for a message like:
```
🔴 Workflow Failed

Workflow: _Test Error
Execution ID: <some-id>
Error: Test error for alert verification
Last Node: Code
Time: 2026-06-05T...
```

If alert arrives within ~10 seconds: ✅ working.

If no alert: see Troubleshooting below.

- [ ] **Step 3: Delete the test workflow**

In n8n UI, delete `_Test Error` workflow (it has no value after testing).

---

### Task 5: Export updated JSONs and commit

After importing and activating, n8n assigns a real ID to the workflow. Export so git-tracked JSONs stay in sync.

- [ ] **Step 1: Export all workflows**

```bash
./scripts/n8n_export.sh
```

Expected: 3 files exported to `secretary/n8n-workflows/` (Auto Sync, Secretary Bot, Secretary Error Alerter).

- [ ] **Step 2: Commit updated JSONs**

```bash
git add secretary/n8n-workflows/
git commit -m "backup(n8n): export workflows after error alerter setup"
```

- [ ] **Step 3: Update daily log**

Append to `secretary/.notes/daily_log.md`:
```markdown
## 2026-06-05

### งานที่ทำ
- สร้าง n8n workflow `Secretary Error Alerter` — Error Trigger → Telegram alert ที่ chat `8663614341`
- Set เป็น global Error Workflow ใน n8n Settings → General → Error Workflow
- ทดสอบด้วย `_Test Error` workflow → ได้รับ alert ใน Telegram ✅

### Architecture Change
- n8n Error Workflow ครอบทุก workflow อัตโนมัติ (Secretary Auto Sync, Secretary Bot, และ future workflows)
- Credential ใช้ "Secretary Bot" telegramApi ตัวเดิม (id: QiUZ8rINLwwPL1qu)
```

```bash
git add secretary/.notes/daily_log.md
git commit -m "docs(secretary): log n8n error alerter setup"
```

---

## Troubleshooting

**Alert not received after test:**

1. Check `Secretary Error Alerter` is toggled **Active** in n8n
2. Check n8n global Settings → Error Workflow shows `Secretary Error Alerter`
3. Go to n8n → Executions → filter by `Secretary Error Alerter` — check if execution appears and whether it shows error
4. Common failure: Telegram credential not valid in the context of this new workflow — open the workflow, click the Telegram node, verify credential shows "Secretary Bot" (not "missing credential")
5. If credential shows missing: open the Telegram node, click the credential dropdown, select "Secretary Bot", save, re-test

**`n8n_import.sh` fails with auth error:**
- Check `N8N_API_KEY` in `secretary/.env` is current (regenerate in n8n UI if needed: Settings → API → Create new key)

**Global Error Workflow setting not found in n8n UI:**

Fallback: set the error workflow per-workflow via the API. For each existing workflow (Auto Sync, Secretary Bot), run:

```bash
source .env.deploy
source secretary/.env
WF_ID="<workflow-id>"
ERROR_WF_ID="<secretary-error-alerter-id>"

ssh -n -i ~/.ssh/id_ed25519 -p 2222 "${NAS_USER}@${NAS_HOST}" \
  "curl -sf -X PATCH 'http://localhost:5678/api/v1/workflows/${WF_ID}' \
    -H 'X-N8N-API-KEY: ${N8N_API_KEY}' \
    -H 'Content-Type: application/json' \
    -d '{\"settings\":{\"errorWorkflow\":\"${ERROR_WF_ID}\"}}'"
```

Workflow IDs visible in n8n UI URL when editing: `https://<host>/workflow/<ID>`.
