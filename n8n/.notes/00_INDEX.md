# n8n — Project Index (Memory Blueprint)

> อัปเดตล่าสุด: 2026-09-08 (แยกออกจาก secretary เป็น stack ของตัวเอง)
> ใช้ไฟล์นี้เป็น cold-start memory ก่อนเริ่มงานทุกครั้ง

---

## Overview

n8n เป็น workflow automation กลางของทั้ง NAS เดิมอยู่ใน `secretary/` (container
`secretary-n8n`) ถูกแยกออกมาเป็น stack ของตัวเองเมื่อ 2026-09-08 เพื่อให้ stack
อื่นเรียกใช้ร่วมกันได้โดยไม่ผูกกับ lifecycle ของ secretary

- image `n8nio/n8n:latest`, container `n8n`, port 5678 → DSM RP :15678
- ไม่มี `depends_on` ไม่มี build ไม่มี volume ร่วมกับใคร

## การเรียก stack อื่น

Workflow ยิงผ่าน published port ของ host:
`http://host.docker.internal:<port>/...` (มาจาก `extra_hosts:
host.docker.internal:host-gateway`)

**ไม่ได้ใช้ shared docker network** — ชื่อ DNS แบบ `secretary-query` resolve ได้
เฉพาะใน compose network ของ stack นั้น ย้ายมาที่นี่แล้วใช้ไม่ได้

ปลายทางที่ใช้อยู่: `http://host.docker.internal:5065/query`,
`http://host.docker.internal:5065/ingest-trigger` (secretary)

## Data

`n8n_data` bind ไปที่ `/volume2/docker/n8n/n8n_data` — ย้ายมาจาก
`/volume2/docker/secretary/n8n_data` ตอนแยก stack (rename ภายใน volume2 =
atomic ไม่ copy) เก็บ workflow, credentials และ encryption key ที่ใช้ถอด
credentials

⚠️ n8n เจอ `.n8n` ว่างเมื่อไหร่ = สร้าง encryption key ใหม่ credentials เก่าถอด
ไม่ออกถาวร **`ls` ยืนยันว่าไดเรกทอรีไม่ว่างก่อน start เสมอ**

`scripts/deploy.sh` chown ไดเรกทอรีนี้เป็น `1000:1000` เพราะ image รันเป็น
`node:node` ไม่ใช่ NAS user

**bind ทำงานจริง (ยืนยัน 2026-09-08)** — `docker volume inspect` โชว์
`Mountpoint` เป็น `/volume2/@docker/volumes/secretary_n8n_data/_data` ซึ่งเคยทำให้
เข้าใจผิดว่า compose `device:` ไม่ได้ map (บันทึก secretary 2026-06-23). วัดแล้ว
device+inode ตรงกันทั้งสอง path = ไฟล์ชุดเดียวกัน mountpoint เป็นแค่จุดที่ docker
เอา bind ไปแปะ

## Reverse proxy / webhook

DSM RP เปลี่ยนเมื่อ 2026-09-08: จาก `n8n.<domain>` port 443 → `<domain>` port
**15678**. `N8N_WEBHOOK_URL` ใน vault (`stacks.secretary.n8n.webhook_url`) กับ
`stacks.homepage.var_n8n_https` แก้ตามแล้ว

⚠️ **n8n ลงทะเบียน webhook กับ Telegram ตอน activate workflow เท่านั้น** เปลี่ยน
`N8N_WEBHOOK_URL` แล้วต้องปิด-เปิด workflow ที่มี webhook trigger ใหม่ ไม่งั้น
Telegram ยิงไป URL เก่าต่อไป บอทเงียบโดยไม่มี error ให้เห็นทั้งฝั่ง n8n และ
Telegram

## Secrets

`n8n/secrets.manifest.yaml` → vault path ยังเป็น `stacks.secretary.n8n.*`
(path ใน vault ไม่จำเป็นต้องตรงชื่อ stack เปลี่ยนแล้วต้อง edit-vault เพิ่มโดย
ไม่ได้อะไรกลับมา)

`N8N_API_KEY` ไม่ได้ใช้ใน compose — `scripts/n8n_export.sh` / `n8n_import.sh`
อ่านจาก `n8n/.env`

## Workflow backup

`n8n/workflows/*.json` git-tracked, export/import ผ่าน REST API + SSH
(`scripts/n8n_export.sh`, `scripts/n8n_import.sh`)

## Cutover checklist (ทำครบแล้ว 2026-09-08 — เก็บไว้เป็นลำดับอ้างอิง)

เรียงตามลำดับ ห้ามสลับ — ขั้น 3-5 คือช่วงที่ data ถูกย้าย ห้ามมี container
ตัวไหนถือ `n8n_data` อยู่

1. `make secrets` (ทำแล้ว — ได้ `n8n/.env`)
2. `./scripts/deploy.sh -y` **อัปไฟล์อย่างเดียว ยังไม่ restart** — จะได้
   `/volume2/docker/n8n/` พร้อม compose บน NAS
   (chown 1000:1000 ในสคริปต์จะยังไม่เจอ `n8n/n8n_data` เพราะยังไม่ย้าย —
   มันกลืน error ด้วย `|| true` ปกติ ขั้น 4 chown ให้เอง)
3. `docker compose --project-directory secretary/ -f secretary/docker-compose.yml down`
   — **`down` เฉยๆ ห้ามใส่ `-v`** ต้อง down ก่อนเพราะ (ก) container
   `secretary-n8n` ตัวเก่าถือ port 5678 และ (ข) มันถือ `n8n_data` อยู่
4. ย้าย data + ยืนยัน + chown:
   ```
   mv /volume2/docker/secretary/n8n_data /volume2/docker/n8n/n8n_data
   ls /volume2/docker/n8n/n8n_data        # ต้องเห็น config, database.sqlite
   chown -R 1000:1000 /volume2/docker/n8n/n8n_data
   ```
   **`ls` ต้องไม่ว่าง** ว่างเมื่อไหร่หยุดทันที อย่า start n8n
   (start ทับ = encryption key ใหม่ credentials ตายถาวร)
5. สร้าง project `n8n` ใน DSM Container Manager ชี้ที่ `/volume2/docker/n8n`
   — **ถ้ามันเสนอให้ pull image ให้ปฏิเสธ** `n8nio/n8n:latest` ไม่ pin version
   ถ้า version กระโดดพร้อมกับตอนแยก stack จะแยกไม่ออกว่าพังเพราะอะไร
   (`up -d` ไม่ re-pull ถ้า image มีอยู่ในเครื่องแล้ว)
6. `up` secretary กลับ
7. **ยืนยัน host-gateway ก่อนแตะ workflow** (docker บน NAS = 24.0.2 รองรับ
   `host-gateway` แต่ยังไม่ได้พิสูจน์ว่า DNAT ของ published port ใช้ได้จริงจาก
   bridge):
   ```
   docker exec n8n getent hosts host.docker.internal
   docker exec n8n node -e 'fetch("http://host.docker.internal:5065/health").then(r=>console.log(r.status))'
   ```
   ใช้ `node -e` ไม่ใช่ curl — image เป็น Alpine อาจไม่มี curl
   ถ้าไม่ผ่าน = ถอยไปใช้ IP ของ NAS ตรงๆ ใน URL แทน (**ยังไม่ import**
   จะได้ไม่ดัน URL พังเข้า instance จริง)
8. `./scripts/n8n_import.sh` ดัน URL ใหม่เข้า instance
9. **ปิด-เปิด workflow ที่มี webhook trigger ใหม่ทุกอัน** (Secretary Bot) —
   `N8N_WEBHOOK_URL` เปลี่ยนเป็น `<domain>:15678` แล้ว แต่ n8n บอก Telegram ว่า
   ให้ยิงมาที่ไหน **เฉพาะตอน activate workflow** เปลี่ยน env เฉยๆ ไม่ย้าย webhook
   ที่ลงทะเบียนไว้แล้ว ไม่ deactivate/activate = Telegram ยิงไป URL เก่าต่อ
   แล้วบอทเงียบโดยไม่มี error ที่ไหนเลย
10. **แก้ Uptime Kuma monitor id 28** (`Secretary N8N`) — เป็น monitor แบบ
   `docker` ผูกกับชื่อ container `secretary-n8n` ซึ่งเปลี่ยนเป็น `n8n` แล้ว
   ไม่แก้ = monitor แดงตลอด. ไม่มี API ต้องแก้ใน DB โดยหยุด container ก่อน:
   ```
   docker stop uptime-kuma
   sqlite3 <kuma.db> "update monitor set docker_container='n8n', name='n8n' where id=28;"
   docker start uptime-kuma
   ```
11. ทดสอบบอท Telegram จริง 1 คำถาม (ต้องผ่านทั้ง credentials เก่าและ
    URL ใหม่ = พิสูจน์ทั้งการย้าย data และ host-gateway ในนัดเดียว)

## หลุมที่ต้องระวังตลอดไป

- **`n8n_data` = single point of failure** เก็บ encryption key ที่ถอด
  credentials ทั้งหมด ไม่มี backup อัตโนมัติ start ทับตอนว่าง = ตายถาวร
- **volume `secretary_n8n_data` ตัวเก่ายังค้างใน docker** หลังย้าย (metadata
  ชี้ path ที่ไม่มีแล้ว) ลบทิ้งได้ด้วย `docker volume rm secretary_n8n_data`
  **หลังยืนยันว่า n8n ตัวใหม่ขึ้นและ credentials ใช้ได้แล้วเท่านั้น**

## Gaps / TODO

- **Uptime Kuma monitor id 28** ยังผูกชื่อ container `secretary-n8n` → แดงตลอด
  (ข้อ 10 ยังไม่ได้ทำ ต้องแก้ใน `kuma.db` ตอน stop container)
- `docker volume rm secretary_n8n_data` ทิ้งได้ (metadata ค้างชี้ path เก่า)
- ขยะบน NAS ที่ deploy ไม่ลบให้: `/volume2/docker/secretary/{n8n-workflows,
  secrets.manifest.yaml,ollama_data}`
- **coupling: homepage-nginx เป็นทางเข้า webhook** homepage ล่ม = บอทไม่ได้รับ
  ข้อความ ตัดได้ด้วยการ forward 8443 ที่ router
- `secretary-ingest` เคยขึ้นค้างทั้งที่เป็น one-shot `restart: "no"` แล้วโดน
  host OOM killer (exit 137) ทำ NAS ล่ม 4 ชม. — ยังไม่ได้ตามว่าใครสั่งมันรัน

## 2026-10-15 — Shop Flow Studio orchestration (local, inactive)

Added `workflows/Shop_Flow_Studio.json` and `docs/shop-flow-studio.md`: minute-based durable render dispatch, bounded wait/status checks and terminal notification recovery. Custom HTTP credential combines existing gateway Basic Auth with scoped X-Shop-Token. Workflow carries job/render metadata only; manual Flow generation/import stays in Shop UI. Worker sends Telegram notices through durable deduplicated commands.

Wiring tests passed locally; final cross-module review PASS. Workflow remains inactive, not imported to NAS; no live credentials/routes or executions tested. No implementation commit/push/deploy. Shared implementation worktree `/private/tmp/shorts-flow-studio`, branch `codex/shorts-flow-studio`.

### Verification follow-up — 2026-10-15

Companion Shop container regression passed: 408 passed, 2 repository-wiring skips (covered by passing local tests), 1 live TTS deselection. Workflow graph/authentication reviewed; local wiring tests passed. Visual Thai usage guide: `../shorts-factory/docs/shop-flow-studio-guide.html`. Workflow still inactive and unimported; live NAS/n8n integration not verified. Implementation uncommitted in task worktree.

## 2026-10-15 - Task closed at user request

Implementation and Thai HTML guide completed locally in `/private/tmp/shorts-flow-studio`, branch `codex/shorts-flow-studio`. Implementation remains UNCOMMITTED; no merge, push, NAS deployment, or live n8n import/activation. HEAD remains design commit `ec2eb27`. Main checkout memory includes this handoff so the next session can find the implementation.

Verification: Docker regression 408 passed, 2 repository wiring tests skipped (passed separately locally), 1 live TTS test deselected. Image build, make check, and final code review passed; no Critical/Important findings. HTML anchors/local links and save/validate/reapprove instructions checked. Browser visual inspection and real Flow/provider acceptance remain unverified.

Next session: resume existing worktree, review/commit full changes, configure public URL and automation credentials, import inactive n8n workflow, deploy through scripts/deploy.sh when requested, and validate a real Flow clip end-to-end on NAS before production acceptance. Local tests do not imply deployment.

Completed Shop_Flow_Studio.json and setup guide. Workflow remains inactive and has not been imported into live n8n.

## 2026-10-15 - Release authorized

User explicitly requested commit to main, push, and deploy. Reopening release work. Preserve prior closure entries as history; current deployment outcome will be recorded after verification. Shop public URL now resolves from vault-managed deployment configuration using the existing Creator Studio external origin. No secrets in workflow JSON.

## 2026-10-15 - Main pushed and NAS deployment completed

Implementation commit `baa021f` fast-forwarded into main and pushed to origin/main (HTTP/2 transport failed once; retry over HTTP/1.1 succeeded). `scripts/deploy.sh -s shorts-factory -y` completed; local deploy ref points at baa021f. Existing data volumes retained. Shop API/worker, legacy bot, dashboard, and nginx all running with restart count 0. Public HTTPS /shop returned 200 with valid authentication; anonymous /shop returned 401. From the real n8n container, Shop page, job list and automation pending all returned 200; pending queue empty.

Deployment uncovered a stale gitignored nginx/.htpasswd (both username and password differed from vault). Backed up the old file locally, regenerated bcrypt from the authoritative vault dashboard credentials, verified, and redeployed through the standard script. No secrets committed. SHOP_PUBLIC_URL is vault-managed and uses the existing Creator Studio external origin.

Live n8n workflow `4uYGddwteUuqsb6j` (Shop Flow Studio) imported via public API with bound encrypted httpCustomAuth credential and all timeout/retention/timezone settings preserved; activated. n8n service was not restarted. Portable workflow JSON deliberately contains no instance-specific credential ID. Generic import helper only preserves executionOrder; documented restoration of the other settings and credential binding.

Release regression: 408 passed, 2 repository-wiring skips covered by 2 passing local tests, 1 live TTS deselection. Browser visual acceptance and a real Flow clip with live TTS remain untested; synthetic HTTP/worker/render/restart/download integration passed. No test Telegram messages or automatic publishing performed. Prior closed/uncommitted/inactive entries above describe earlier states and are superseded by this release entry.

Scheduler verification: successful GET /shop/automation/pending requests increased from 2 to 3 while no additional smoke requests were sent, with workflow active and queue empty. Worker logs contained no traceback. Successful executions are not retained by configured policy, so an empty executions list is expected. Real Flow/video/TTS production acceptance still remains.

## Clip Intake (Hermes) — `IYayiImdn0Jd5yMS` (2026-10-27)

`POST /webhook/clip-request` (public path) → `Record job` gate → `Respond accepted` → `Sign for Hermes`
(HMAC `HERMES_CLIP_WEBHOOK_SECRET`, POST `https://<domain>/webhooks/clip` → homepage nginx →
`host.docker.internal:8644`). Caller (Hermes) must send `X-Clip-Token` = `CLIP_INTAKE_TOKEN`
(vault `stacks.secretary.n8n.clip_intake_token`); empty env = reject all. Field rules + full flow:
`docs/clip-intake.md`. Error workflow = Secretary Error Alerter. n8n env now has
`N8N_BLOCK_ENV_ACCESS_IN_NODE=false` + `NODE_FUNCTION_ALLOW_BUILTIN=crypto,http,https` (every Code node
can read all env). `scripts/n8n_import.sh` now preserves accepted settings keys (was executionOrder only).

⚠️ Without the token check this URL is an unauthenticated prompt-injection path to a Hermes terminal
(found live 2026-10-27). Never import a Clip Intake JSON without the `Record job` gate.

Status 2026-10-27: deployed + verified end to end (ping 21229 → 202 route `clip`; no-token 21231 → 401
skipped; 401 also on `:15678`). No real clip through this path yet.

Gaps: once Hermes answers 202 n8n tracks nothing — a gateway restart mid-run loses the job silently.
`Hermes Bridge Probe` is deactivated (not deleted). `HERMES_WEBHOOK_SECRET` in n8n env/manifest is unused
(drop + redeploy n8n). Domain is hardcoded in `Sign for Hermes` (could derive from `$env.N8N_WEBHOOK_URL`). Uptime Kuma monitor id 28 still open (see above).
