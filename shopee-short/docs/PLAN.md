# โปรเจกต์: `shopee-short` — Shopee Affiliate ผ่านคลิปสั้น (ทดลองตลาดก่อน แล้วค่อยสร้าง stack)

## 1. เป้าหมาย

ได้ค่าคอม Shopee Affiliate จากคลิปสั้นโดยเจ้าของออกแรงน้อยที่สุด แต่**ห้ามสร้าง stack ก่อนพิสูจน์ว่ามีคนคลิกจริง** งานแบ่งเป็นด่าน แต่ละด่านมีเกณฑ์ผ่าน ไม่ผ่าน = หยุดแล้วรายงาน ไม่ทำด่านถัดไป

อ่าน `CLAUDE.md` ที่ root ก่อนเริ่ม กติกา repo ทั้งหมดอยู่ในนั้น prompt นี้ไม่เขียนซ้ำ

## 2. ข้อเท็จจริง (ระดับความเชื่อถือกำกับไว้ทุกข้อ)

**แหล่งปฐมภูมิ (YouTube Help) — เชื่อได้**
- ลิงก์ในคำอธิบายและคอมเมนต์ของ **Shorts กดไม่ได้** (ตั้งแต่ 31/08/2023 ทุกช่อง ทุกประเทศ) ที่ยังกดได้: คำอธิบาย/คอมเมนต์ของคลิปยาว, ลิงก์ใน About ของช่อง, ปุ่ม **Related Video** บน Shorts ที่ชี้ไปคลิปยาว
- **YouTube Shopping affiliate เปิดในไทยแล้ว** (Shopee เป็นพาร์ทเนอร์ ตั้งแต่ ต.ค. 2024) แท็กสินค้าได้ ≤30 ชิ้นต่อคลิป และคลิกได้แม้ใน Shorts **แต่ช่องต้องอยู่ใน YPP ก่อน** เกณฑ์อยู่ที่ https://support.google.com/youtube/answer/13376398 — เช็คจากหน้านี้เอง ห้ามใช้ตัวเลขจากบล็อก

**แหล่งรอง (SDK ชุมชน / explorer ของประเทศอื่น) — ต้อง verify ใน Phase 0**
- Shopee Affiliate Open API เป็น **GraphQL endpoint เดียวต่อประเทศ** ของไทยคือ `https://open-api.affiliate.shopee.co.th/graphql` — **endpoint ตอบจริง** (12/10/2026 ยิงด้วย creds ปลอมได้ `error [10020]: Invalid Credential` รูปแบบ error ของ Shopee) ยังไม่ได้ยิงด้วย creds จริง
- operations: `productOfferV2`, `shopOfferV2`, `shopeeOfferV2`, `generateShortLink` (รับ `subIds`), `generateBatchShortLink`, `conversionReport`, `validatedReport`
- auth: header `Authorization: SHA256 Credential=<appId>,Timestamp=<unix วินาที>,Signature=<sha256_hex(appId+timestamp+body+secret)>` — **body ที่ hash ต้องเป็นไบต์เดียวกับที่ส่ง** (serialize ครั้งเดียว) ไม่งั้นได้ `10020 Invalid Signature`
- `productOfferV2` คืนมากกว่า "title/ภาพ/ราคา" (มี `commissionRate`, `offerLink`, `priceMin`, `priceDiscountRate` ฯลฯ) — field จริงให้ดูจาก explorer/การยิงจริง

**ความจำ ไม่ได้ verify — อย่าออกแบบโดยพึ่งข้อนี้จนกว่าจะเช็ค**
- `videos.insert` กิน 1600 quota units, quota default 10,000/วัน/โปรเจกต์
- YouTube Data API **ไม่มี** endpoint แท็กสินค้า Shopping และ**ไม่มี** pin comment
- อัตราค่าคอม Shopee — ดูในหน้า dashboard affiliate เอง ไม่มีผลต่อโค้ด

**ผลที่ตามมา:** ช่องใหม่ยังไม่อยู่ใน YPP = ใน Shorts มีทางคลิกที่ verify แล้วแค่ 2 ทาง คือ (ก) Related Video → คลิปยาวที่มีลิงก์ในคำอธิบาย (ข) ลิงก์ใน About ของช่อง ส่วน Shopee Video (แท็กสินค้าในแอป) กับ Facebook Reels ยังไม่ได้ verify ว่าลิงก์กดได้/นับค่าคอมได้

## 3. Phase 0 — verify (ยังไม่เขียนโค้ด stack)

ทำทีละข้อ รายงานผลทุกข้อพร้อมหลักฐาน

1. **Open API ใช้ได้ไหม**: ผู้ใช้ login `affiliate.shopee.co.th` → Open API → สร้าง App ID + Secret (ถ้าต้องสมัคร/รออนุมัติ = รายงานแล้วหยุด) → ใส่ vault ที่ `stacks.shopee_short.shopee.{app_id,secret}` ผ่าน `make edit-vault` (ผู้ใช้ทำเอง)
2. **Probe script** (`shopee-short/scripts/probe.py`, stdlib/httpx, รันบน workstation อ่าน secret จาก env ไม่ hardcode): ยิง `generateShortLink` 1 ลิงก์พร้อม `subIds:["probe"]`, ยิง `productOfferV2` ด้วย keyword 1 คำ, ยิง `conversionReport` ช่วง 7 วัน → บันทึก field ที่ได้จริงลง `shopee-short/.notes/00_INDEX.md` (ห้ามบันทึกค่า secret)
3. **ยืนยันว่าตามรอย subId ได้** — ตัวแยกว่าคลิปไหนทำเงิน ถ้าไม่ได้ การวัดผลรายคลิปใช้ไม่ได้ ให้รายงานก่อนไปต่อ. `conversionReport` มีแถวเฉพาะเมื่อมี order จริง บัญชีใหม่จะว่าง จึงแยกเช็คสองแบบ:
   - **โครงสร้าง:** `schema` ต้องเห็น field ใน node ของ ConversionReport ที่พก subId (`utmContent` เป็นแค่การเดา)
   - **พฤติกรรม:** กดลิงก์จาก `link <url> probe` เอง แล้วดูว่ารายงานคลิกใน dashboard ของ Shopee แยกตาม Sub ID ไหม (ความจำ ต้อง verify)
   - กดลิงก์ตัวเองได้ แต่**ห้ามซื้อเองเพื่อบังคับให้มี conversion** น่าจะผิดข้อตกลง affiliate
4. **ช่องทางที่กดได้จริง**: เช็คสถานะ YPP ของช่องที่จะใช้ + ลอง verify Shopee Video/FB Reels ว่าแนบ affiliate link แล้วกดได้และนับค่าคอม (ทำได้แค่ไหนรายงานแค่นั้น อย่าเดา)
5. **ช่อง YouTube ใหม่ แยกจาก shorts-factory** (ถ้าโดนนโยบาย reused/inauthentic content จะได้ไม่ลามช่องหลัก)
6. **Housekeeping พอร์ต** (ตรวจแล้ว 12/10/2026): `:15067` คือ DSM Reverse Proxy entry ค้าง → `localhost:5067` ที่ไม่มีอะไรฟังอยู่ (ของ `wallpaper-scout` ที่ถูกลบไปแล้ว) ผู้ใช้ลบเองใน DSM Login Portal → Advanced → Reverse Proxy ถ้าต้องการ — agent ห้ามแก้ RP เอง (พลาด = 443 ล่มทั้งเครื่อง)

**เกณฑ์ผ่าน Phase 0:** สร้างลิงก์ด้วย API ได้ + subId ตามรอยได้ + มีอย่างน้อย 1 ช่องทางที่ลิงก์กดได้จริง
**ผลจริง 12/10/2026: บัญชีไม่มีสิทธิ์ Open API ต้องติดต่อ Shopee ขอ** → ใช้ทางนี้ระหว่างรอ.
**ไม่ผ่าน (API ไม่เปิด):** fallback = ผู้ใช้สร้าง custom link + Sub ID ("ลิงก์ที่กำหนดเอง") + เลือกสินค้าจาก "รายการ feed สินค้า" ในหน้า dashboard ของ Shopee เอง (ด่านถัดไปยังทำได้)

## 4. Phase 1 — ทดลองตลาดด้วยมือ 2 สัปดาห์ (ไม่มี stack)

- คลิป 8–10 อัน **ทำด้วยวิธีไหนก็ได้** (CapCut, Gemini, Flow ฯลฯ) — ด่านนี้ทดสอบว่า**ช่องทางนี้ขายได้ไหม** ไม่ได้ทดสอบ pipeline
- **คลิปทดลองทำด้วย `/shop` ใน shorts-factory** (ADR 0015, 13/10/2026 — กลับคำจากเดิมที่ห้าม): โหมดแยกจาก Topic ไม่มีปุ่มอัป ตัวเลขเช็คกับ Brief ที่คนส่ง ไม่มี Manifest/Experiment/dashboard ส่วน Topic ปกติยังห้ามใช้ทำคลิปสินค้าด้วยเหตุผลเดิม
- ทุกคลิปใช้ลิงก์ที่มี **subId ไม่ซ้ำกัน** (เช่น `t01`…`t10`) จดในตาราง `shopee-short/.notes/experiment.md`: subId, สินค้า, ช่องทาง, วันโพสต์
- ถ้าโพสต์ YouTube ช่องที่ยังไม่อยู่ใน YPP: ทางที่ประกอบจากของที่ verify แล้วคือ **Shorts → Related Video → คลิปยาวสรุปสินค้ารายสัปดาห์** ที่มีลิงก์ subId ในคำอธิบาย (ทางเลือก ไม่ใช่คำตอบ เลือกตามผล Phase 0 ข้อ 4)
- จบ 2 สัปดาห์: ดึงตัวเลขตาม subId (คลิก, order, ค่าคอม) + ยอดวิว → สรุปใน `.notes/experiment.md`

**เกณฑ์ผ่าน Phase 1 (ผู้ใช้ตัดสินจากตัวเลข):** ตั้งตัวเลขไว้**ก่อน**เริ่มทดลอง แล้วบันทึกลง `experiment.md` (ข้อเสนอ: ≥1 order ที่มาจาก subId หรือ ≥50 คลิกรวม) ไม่ถึง = หยุด ไม่สร้าง stack

## 5. Phase 2 — สร้าง stack `shopee-short/` (เฉพาะเมื่อผ่าน Phase 1)

ทำบน branch `feature/shopee-short` ตัดสินใจใหญ่ทุกข้อเขียน ADR ที่ `docs/adr/` (เลขถัดไปคือ **0015**)

**แบบเดียวกับ shorts-factory** (เจ้าของใช้มือถือเป็นหลัก ทุกอย่างที่ต้องใช้คนต้องจบใน Telegram):
- บอท Telegram `getUpdates` long-poll ไม่มี HTTP (ADR 0002) ใช้ `shared/telegram.py` — **bot token ใหม่ของตัวเอง** (แชร์กับ shorts = แย่ง `getUpdates`)
- approve = ปุ่มใต้คลิปใน Telegram ไม่ใช่เว็บ แก้สคริปต์ = พิมพ์ feedback ตอบกลับ
- dashboard (ถ้าทำ) = container แยก read-only หลัง nginx basic auth (ADR 0007) พอร์ต **5073 / 15073** (เช็คแล้วว่าว่างบน NAS)
- ตารางเวลาใช้ APScheduler หรือ poll loop ไม่ใช้ cron
- LLM = `shared/mimo.py` ตัวเดียว (`shared.llm.mimo_api_key` มีใน vault แล้ว) ไม่ต้องรองรับหลายเจ้า

**ส่วนประกอบ**
1. **selector** — รายสัปดาห์ `productOfferV2` ตาม keyword/หมวดใน config → กรองตาม field ที่ Phase 0 ยืนยันว่ามี → SQLite, dedup ด้วย itemId (ไม่เคยทำคลิปสินค้าเดิมซ้ำ)
2. **factory** — สคริปต์ (mimo) + TTS + ภาพสินค้า + ffmpeg 9:16 + ซับ + BGM, ลิงก์ `generateShortLink` ด้วย **subId = clip_id**, ข้อความเปิดเผยว่าเป็น affiliate/`#ad`
   - **ห้าม copy-paste `shorts-factory/app/render.py`** ตัวนี้ import `app.footage`, `app.locales` จึง `make sync-shared` ตรงๆ ไม่ได้ → งานแยก: ยกส่วนที่ใช้ร่วม (TTS, การ์ด Pillow, ffmpeg compose) ขึ้น `shared/` + เทสต์ shorts-factory ยังเขียวเท่าเดิม + ADR 0015 ถ้าแยกไม่คุ้ม ADR ต้องบอกเหตุผล
   - Dockerfile ต้องมี `libraqm0`, `fonts-thai-tlwg` และ assert `features.check('raqm')` ตอน build (ดูแถว shorts-factory ใน CLAUDE.md)
   - กันคลิปซ้ำแบบวัดได้: similarity ของสคริปต์ใหม่กับ 30 อันล่าสุดต้องต่ำกว่าเกณฑ์ที่ตั้งใน config ไม่ผ่านให้เขียนใหม่
3. **ปลายทาง** — ตามช่องทางที่ผ่าน Phase 1:
   - ไม่ได้อัปผ่าน API: ส่ง mp4 + caption + ลิงก์ เข้า Telegram ให้คนโพสต์เอง (~1 นาที/คลิป)
   - อัป YouTube ผ่าน API: อ่าน ADR 0001 + 0008 ก่อน (audit = ถูกบังคับ private, consent `Testing` = token ตาย 7 วัน), **โปรเจกต์ GCP แยก** (quota นับต่อโปรเจกต์), ใช้แพตเทิร์น credential ต่อช่องแบบ ADR 0008, อ่าน `privacyStatus` ที่ API ตอบกลับ cap ≤2 คลิป/วัน — การแท็ก Shopping ทำผ่าน API ไม่ได้ (ความจำ ต้อง verify) คนต้องแท็กใน Studio เอง
4. **reporter** — รายสัปดาห์ `conversionReport` group by subId → ผูกกลับ clip_id → Telegram (+LINE ผ่าน `shared/notify.py`) แจ้งเตือนเมื่อคิวว่าง/pipeline พัง

**กับดัก repo ที่ CLAUDE.md ไม่ได้เขียนไว้ตรงๆ**
- `.claude/commands/add-stack.md` ยังบอกให้สร้าง `.env.example` = ล้าสมัย ใช้ `secrets.manifest.yaml` แทน และ**ใส่ค่าใน vault ก่อน แล้วค่อยเพิ่มคีย์ใน manifest** (ลำดับกลับ = `make secrets` พังทั้ง repo) + `make sync-test-vault`
- เพิ่ม `shopee-short` ใน `ALL_STACKS` ของ `scripts/deploy.sh` และ deploy ด้วย `-y` เสมอ (ไม่มี TTY = ข้ามการอัปโหลดเงียบๆ)
- `cpus:` ใช้ไม่ได้บน DSM คุมที่ `-threads` ของ ffmpeg, ใส่ `mem_limit`
- ตรวจ secret ด้วย `/check-secrets` (ไม่มีสคริปต์ชื่อ `scripts/secrets`)

## 6. Acceptance criteria (Phase 2)

- [ ] กด approve ใน Telegram 1 ครั้ง → คลิปไปถึงปลายทางที่เลือก**พร้อมลิงก์ที่กดได้จริงบนช่องทางนั้น**และมี subId = clip_id (ถ้าปลายทางต้องให้คนโพสต์/แท็กเอง ให้นับเวลาที่คนใช้จริงต่อคลิป และต้องไม่เกิน 2 นาที)
- [ ] รันทิ้ง 7 วันโดยไม่มีคนดูแล: ไม่มี exception ที่ไม่ถูกจับใน log, report รายสัปดาห์มาครบ, คิวว่างแล้วมีแจ้งเตือน
- [ ] report บอกค่าคอมรายคลิปได้ (subId → clip_id)
- [ ] cap ≤2 คลิป/วัน มีเทสต์, similarity gate มีเทสต์
- [ ] `/check-secrets` ผ่าน, ไม่มี `.env` ใน git
- [ ] เทสต์ shorts-factory ยังเขียวหลังยกโค้ดขึ้น `shared/` + `tests/test_shared_sync.py` ผ่าน
- [ ] docs ครบตาม `CLAUDE.md` (stack README, แถวตาราง CLAUDE.md + root README พร้อมพอร์ต 5073/15073, `.notes/daily_log.md` + `.notes/00_INDEX.md`)

## 7. ยังไม่ verify (เช็คตอนถึงด่านนั้น)

- endpoint ไทย + field จริงของ `productOfferV2`/`conversionReport` (Phase 0)
- บัญชี affiliate ทั่วไปเปิด Open API ได้เลย หรือต้องขออนุมัติ (Phase 0)
- Shopee Video / FB Reels ลิงก์กดได้และนับค่าคอมไหม (Phase 0)
- เงื่อนไขของ Shopee เรื่องโปรโมตอัตโนมัติ/ใช้ AI ทำคอนเทนต์ (อ่านข้อตกลง affiliate ก่อน Phase 2)
- นโยบาย YouTube เรื่อง inauthentic/reused content กับคลิปสินค้าที่ใช้ภาพนิ่ง + TTS (ก่อน Phase 2)
- quota cost ของ `videos.insert` และเรื่องไม่มี API แท็ก Shopping/pin comment (ก่อนทำ uploader)
