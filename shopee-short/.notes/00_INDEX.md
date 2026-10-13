# shopee-short index

**สถานะ: Phase 0 (verify) — ยังไม่ใช่ stack** (2026-10-12) — **บัญชีไม่มีสิทธิ์ Open API** (หน้า `/open_api`: AppID `--`, ปุ่มเทา, "คุณไม่ได้รับสิทธิ์ในการเข้าถึง Shopee Affiliate Open API Platform หากต้องการเข้าใช้งาน กรุณาติดต่อเรา") → ทำ Phase 1 ด้วย fallback (ลิงก์ที่กำหนดเอง + รายการ feed สินค้า) ระหว่างรอขอสิทธิ์. ไม่มี `docker-compose.yml` ไม่อยู่ใน `ALL_STACKS` ไม่อยู่ในตาราง `CLAUDE.md` (doc-drift checker นับเฉพาะ dir ที่มี compose) จะสร้าง stack ก็ต่อเมื่อผ่าน Phase 1 — แผนเต็มอยู่ที่ `docs/PLAN.md`

## คืออะไร

Shopee Affiliate ผ่านคลิปสั้น แบ่งเป็นด่าน: Phase 0 verify API/ช่องทาง → Phase 1 ทดลองตลาดด้วยมือ 2 สัปดาห์ (subId ต่อคลิป) → Phase 2 สร้าง stack (Telegram approve แบบ shorts-factory)

## สิ่งที่รู้แล้ว

- **Endpoint TH** `https://open-api.affiliate.shopee.co.th/graphql` ตอบจริง — creds ปลอมได้ `error [10020]: Invalid Credential` (12/10)
- **ลิงก์ใน Shorts กดไม่ได้** (YouTube Help) — ทางที่กดได้: คลิปยาว, About ของช่อง, Related Video บน Shorts, Shopping tag (ต้องอยู่ใน YPP)
- **คลิปทำด้วย `/shop` ใน shorts-factory** (ADR 0015 กลับคำเดิมที่ห้าม): ส่งรูป+ข้อความ → Pitch → mp4 + caption โพสต์เอง ดู `shorts-factory/README.md` "Product Clips" — Topic ปกติยังห้ามใช้ทำคลิปสินค้า
- **พอร์ตจองไว้ 5073/15073** (ว่างบน NAS ตรวจ 12/10). `:15067` = DSM RP entry ค้างชี้ `localhost:5067` (ของ wallpaper-scout ที่ลบไปแล้ว) ไม่มี backend — ให้ผู้ใช้ลบเองใน DSM
- README root ไม่ตรงเครื่องจริง: `my-secretary` (`/volume2/docker/my-secretary`, ไม่อยู่ใน repo) ถือ `5057` — ยังไม่ได้แก้
- **⚠️ `:15069` = DSM RP → dupe-sweeper `5069`** แต่ CLAUDE.md/README บอก LAN only (เหตุผลที่ยอมให้รันเป็น root + mount media read-write) ถ้า router forward 15069 = dashboard ที่ลบไฟล์ได้เปิดออกเน็ต มีแค่ basic auth กั้น — แจ้งผู้ใช้แล้ว ยังไม่ได้แตะ RP/router

## Probe

`scripts/shopee_probe.py` (stdlib ล้วน รันบน workstation): `schema` / `link <url> [subId]` / `offers <keyword>` / `report [days]` อ่าน `SHOPEE_APP_ID` `SHOPEE_SECRET` จาก env ไม่ print secret. Signature = `sha256(appId + ts + body + secret)` hash ไบต์เดียวกับที่ส่ง. field ใน query มาจาก SDK ชุมชน — รัน `schema` ก่อนเสมอ field ผิดตัวเดียว query ล้มทั้งก้อน. เทสต์ `tests/test_probe.py` (6)

รันจาก root ของ repo ดึง creds จาก vault เข้า env (ห้ามพิมพ์ secret ตรงๆ ในคำสั่ง = ติด shell history):

```bash
export SHOPEE_APP_ID=$(sops -d --extract '["stacks"]["shopee_short"]["shopee"]["app_id"]' secrets/vault.sops.yaml)
export SHOPEE_SECRET=$(sops -d --extract '["stacks"]["shopee_short"]["shopee"]["secret"]' secrets/vault.sops.yaml)
python3 shopee-short/scripts/shopee_probe.py schema
```

`sops -d` ไม่ผ่าน → เช็ค `SOPS_AGE_KEY_FILE` / `~/.config/sops/age/keys.txt`

## Secrets (วางแผน)

`stacks.shopee_short.shopee.{app_id,secret}` — ยังไม่มีใน vault. ใส่ด้วย `make edit-vault` แล้ว `make sync-test-vault` + `make check`. **ห้ามสร้าง `secrets.manifest.yaml` ก่อนมีค่าใน vault** (`make secrets` พังทั้ง repo)

## Phase 0 ค้าง (ผู้ใช้ต้องทำ)

1. ~~สร้าง App ID~~ ทำไม่ได้ — ต้องกด "ติดต่อเรา" ขอสิทธิ์ (กรอกข้อมูลการชำระเงินและภาษีให้ครบก่อน แถบแดงยังขึ้นอยู่). ระหว่างรอ: เช็ค subId ด้วย "ลิงก์ที่กำหนดเอง" + "รายงานคลิก" (อัปเดต 15:30 ทุกวัน)
2. รัน probe: `schema` → `link` → `offers` → `report` บันทึก field จริงที่นี่
3. ยืนยันตามรอย subId: `schema` เห็น field ที่พก subId ใน ConversionReport + กดลิงก์ `probe` เองแล้วดูรายงานคลิกใน dashboard แยกตาม Sub ID (`conversionReport` บัญชีใหม่ว่างจนกว่าจะมี order — ห้ามซื้อเองเพื่อเทสต์)
4. ตัดสินใจช่องทางที่กดลิงก์ได้ + ช่อง YouTube ใหม่แยกจาก shorts
