# Shop Flow Studio orchestration

Import `n8n/workflows/Shop_Flow_Studio.json` after deploying the Shop services. The saved workflow is inactive. It uses no Telegram Trigger and never receives video bytes.

## Credential

Create an **HTTP Custom Auth** credential named **Shop Flow Studio**. Its JSON contains two headers:

```json
{
  "headers": {
    "Authorization": "Basic <base64-of-dashboard-user:dashboard-password>",
    "X-Shop-Token": "<SHOP_AUTOMATION_TOKEN>"
  }
}
```

Dashboard credentials remain at `stacks.shorts_factory.dashboard.*`; the scoped token lives at `stacks.shorts_factory.shop.automation_token` in the SOPS vault and is rendered into shorts-factory/.env. Enter values into the credential UI or an approved credential import; never put them in workflow JSON, notes or command output. Basic Auth remains enforced by nginx; a token alone does not bypass it. Select this credential on every HTTP node after import. Keep credential export out of Git.

## Operation

Every minute, query `http://host.docker.internal:5071/shop/automation/pending`. Pending renders start idempotently by immutable render ID and revision. Queued/running work waits 30 seconds and checks status once. Ready/failed work requests a deduplicated Telegram notification from the Shop worker. An unfinished check ends this execution; the next scheduled reconciliation continues. No execution waits indefinitely. HTTP errors retry three times, then the next scheduled run recovers.

Terminal work remains discoverable until its notification is queued/running/successful, allowing recovery if n8n restarts between completion and notification. Worker records and controls notification retries. Do not map input binaries or product brief into workflow nodes. Only IDs and status are needed.

## Bring-up

1. Start Shop API/worker and nginx with the new configuration. Existing host port remains 5071; no additional DSM proxy entry.
2. Set `SHOP_PUBLIC_URL` to the actual external Creator Studio origin (scheme, host, optional port; no `/shop` suffix), then recreate worker. This makes Telegram job links clickable. Leave empty for local development only.
3. Import this workflow with `scripts/n8n_import.sh n8n/workflows/Shop_Flow_Studio.json`; import/update does not constitute a runtime test. Check whether an existing workflow retained active state before editing.
4. Bind credentials and run manually against an approved test render. Confirm only one render starts across duplicate executions and one notification arrives.
5. Activate after the manual test. Stop or deactivate orchestration to pause new render dispatch; existing render commands may finish.

For a local smoke test, call the same automation endpoints using test-only credentials. Never claim a live NAS/n8n activation based on local tests.

Official node references: https://docs.n8n.io/integrations/builtin/credentials/httprequest/ and https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/.

## Import settings check

The generic `scripts/n8n_import.sh` helper retains only `executionOrder`. After using it, restore `executionTimeout=240`, `saveDataSuccessExecution=none`, `saveDataErrorExecution=all`, and `timezone=Asia/Bangkok` from the workflow JSON before activation. Direct public API import can preserve these settings in its payload. Always bind the credential ID after importing the portable workflow.
