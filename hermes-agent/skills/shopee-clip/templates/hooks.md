# Hook rotation — vary the opener per clip without inventing one each time

Pick ONE hook per clip by category with `perf.py pick-hook --category <cat>` (least recently used over the
clip-log rows AND every storyboard that carried an id of the same family), put its id on the board stamp
(`clipjob.py board <job> --hook-id <id>`, every board) and in the deliver row (`--hook-id`).

Rule: never reuse a `hook_id` for the same category within 5 consecutive rows.

**Same-date ties break on FILE ORDER.** The log records a date, not a time, so when every candidate's most recent use carries the same `date`, LRU picks the id whose last row sits EARLIEST in the file — that is the least-recently-used one, and the wording tie-break below only applies after that.

**The 5-row rule bends for small families:** `perf.py` excludes at most (candidates − 2) recent ids, so a 6-hook
category keeps 2 eligible. Take its pick — do not stall or invent a new id. Only when the pick is wrong for the
product does a tie-break matter: prefer the eligible id whose wording the product actually fits.

**A VO opener that is NOT one of the templates below gets a `custom-<slug>-N` id** (written bespoke for
the clip from the ad/creative): template ids exist to track template rotation, so logging a template id
the VO never spoke corrupts that category's LRU. Slug = short product/job name; N counts the product's
clips. This includes when LRU lands on a template whose wording plainly does not fit the product (a
before/after hook for a product with no before state): write the opener from the ad's own creative and
log the custom id — rotation never justifies a mismatched hook.

## เกม / ตลับเกม (`game`)
**กติกาใหม่ของ Fix (2026-10-28): คลิปแผ่นเกมห้ามใช้ hook/เสียงพากย์แนวนี้ "วางบนชั้นแล้วเพื่อนทักทุกครั้งที่มาบ้าน"** (ใช้ไปแล้วในคลิป FINAL FANTASY RESONANCE — เขาสั่งเลิกเด็ดขาด) ให้ hook + voiceover พูดถึง **ตัวเกม** แทน: แนวเกม (RPG / แอคชัน / ผจญภัย / สยองขวัญ / ไฟต์เตอร์ / แข่งรถ / จำลองสถานการณ์), เนื้อเรื่อง, เกมเพลย์ หรือระบบการเล่น — แนวเกมนั้น **หาจาก `web_search` ครั้งเดียว** (ชื่อเกม + publisher/แพลตฟอร์มทางการ): ลิสติ้ง Shopee อ่านไม่ได้เพราะ WAF จึงเป็นแหล่งข้อมูลที่ใช้ไม่ได้จริง, และผลค้นหาทางการยืนยันได้ทั้ง แนวเกม + วันวางจำหน่าย (ใช้เป็นวันที่ในคลิปได้) + ภาษาที่รองรับ (ใช้ยืนยัน region/language ที่ Fix ส่งมา) แล้วเติมลง `<แนวเกม>` ใน hook ที่เป็น template — **ค้นครั้งแรกให้ใช้ภาษาของ publisher ด้วย**: query ชื่อเกมภาษาอังกฤษล้วนคืนผลว่างได้จริงสำหรับเกมที่ marketing ญี่ปุ่น (เช่น FINAL FANTASY RESONANCE ค้นอังกฤษได้ 0 รายการ แต่ `ชื่อเกม + スクウェア・エニックス + 発売日` ได้ press release ทางการทันที) ซึ่งให้ แนวเกม (ジャンル) + วันวางจำหน่าย + ตาราง対応言語 ที่ยืนยัน region/language ของตลับที่ Fix ส่งมา — ถ้า query แรกคืนว่าง ให้สลับภาษาอีกครั้งเดียวแล้วหยุด อย่าวนลูป

**Fix 2026-11-26: "คำ hook ซ้ำๆ ตลอด น่าเบื่อ"** (ตัวอย่างที่เขายก: "เบื่อเกมจำเจเดิมๆ อยู่ใช่ไหม") — เดิมมีแค่ 4 ประโยค
ใช้ไป 30 คลิป และ `game-2` "เบื่อเกมเดิมๆ ที่เล่นยังไงก็จำเจอยู่ไหม?" ขึ้นบอร์ดซ้ำ 3 ครั้งใน 12 วัน (gundam-ro 11-14,
gotg 11-20, metroid 11-26) เพราะทุกครั้งที่ฟิกสั่งแก้ แถว log เป็น custom id แล้ว template ไม่เคยแก่ลง. กติกา:
- **ทุก hook ต้องมีของที่เกมนี้มีเกมเดียว** — ชื่อซีรีส์ / เนื้อเรื่อง / ตัวเอก / ระบบเด่น / โลกของเกม / จำนวนผู้เล่น /
  แพลตฟอร์มที่เพิ่งมาลง — มาจาก `web_search` ครั้งเดียวข้างบน หรือจากชื่อสินค้าเอง. ประโยคที่ยกไปใส่เกมอื่นได้ทั้งดุ้น
  = ใช้ไม่ได้ ให้ข้ามไป id ถัดไปที่ข้อมูลครบ.
- **ห้าม:** "เบื่อเกมเดิม / จำเจ / เกมซ้ำๆ" ทุกรูปแบบ, "เกมแนวนี้" ลอยๆ ไม่บอกแนว, "ของมันต้องมี" เปิดคลิป, และชั้นวาง/เพื่อนทัก (กฎ 10-28).
- **ยาว ≤ ~36 ตัวอักษร** (นับแบบ `vo_rate`: ก-๙ + ละติน/ตัวเลข ≈ 3 วิ) — hook เป็นแค่ต้นประโยคของช็อต 1 ที่เหลือต้องพอให้จุดขาย.
- เลือก id ด้วย `perf.py pick-hook --category game` แล้วส่ง id เดียวกันใน `clipjob.py board <job> --hook-id <id>`
  ทุกบอร์ด: picker นับทุกบอร์ดเป็นการใช้ (ฟิกเปลี่ยนเป็นประโยคของเขาเอง template นั้นก็ถือว่าใช้ไปแล้ว). id ที่ได้มา
  แต่ข้อมูลไม่ครบ (ไม่มีซีรีส์ / ไม่มี co-op) → `--candidates` เฉพาะ id ที่ข้อมูลครบ แล้วรันใหม่.

| id | ประโยคเปิด (เติม `<…>` จากผลค้น) | ต้องมีจากแหล่ง | ตัวอย่าง |
|---|---|---|---|
| `game-1` | "แฟน <ซีรีส์> ภาคนี้ต้องมีติดเครื่อง" | เกมเป็นภาคหนึ่งของซีรีส์จริง | แฟน Metroid ภาคนี้ต้องมีติดเครื่อง |
| `game-2` | "ถ้าต้อง<สถานการณ์ของเกม> จะรอดไหม" | เนื้อเรื่อง/สถานการณ์เปิดเกม ≤6 คำ | ถ้าต้องติดอยู่บนดาวสัตว์ประหลาด จะรอดไหม |
| `game-3` | "เกมนี้ได้เล่นเป็น<ตัวเอก/บทบาท>" | ตัวเอกหรือบทบาทผู้เล่น | เกมนี้ได้เล่นเป็นนักล่าค่าหัวในชุดเกราะ |
| `game-4` | "เกมนี้<ระบบเด่น>ได้ด้วยนะ" | ระบบการเล่นที่ทางการโปรโมต 1 อย่าง | เกมนี้ม้วนตัวเป็นลูกบอลกลิ้งหนีได้ด้วยนะ |
| `game-5` | "พาไปเดินเล่นใน<โลกของเกม>กัน" | ฉาก/ยุค/โลกของเกม | พาไปเดินเล่นในญี่ปุ่นยุคซามูไรกัน |
| `game-6` | "ใครชอบ <เกมที่คล้าย> ตัวนี้ต้องลอง" | เกมดังแนวเดียวกันที่เทียบได้ชัด (ไม่มี = ข้าม) | ใครชอบ Hollow Knight ตัวนี้ต้องลอง |
| `game-7` | "ชวนเพื่อนมาเล่นด้วยกันได้<จำนวน>คน" | multiplayer/co-op + จำนวนคน (พูดเป็นคำ) | ชวนเพื่อนมาเล่นด้วยกันได้สี่คน |
| `game-8` | "<ชื่อเกมสั้น> มาลง <แพลตฟอร์ม> แล้ว" | ฉบับแพลตฟอร์มนี้วางขายไม่เกิน 12 เดือน | Oblivion ฉบับรีมาสเตอร์ มาลง Switch 2 แล้ว |
| `game-9` | "<ชื่อเกมสั้น> ตลับนี้มีอะไรให้เล่น ดูกัน" | ชื่อเกมจากชื่อสินค้า (ตัวสำรองเมื่อค้นไม่เจออะไร) | Metroid ตลับนี้มีอะไรให้เล่น ดูกัน |

ตัวอย่างในตารางห้ามพูดตามคำต่อคำกับเกมอื่น — เป็นแค่รูปประโยค. ชื่อเกม/ซีรีส์อังกฤษพูดตามที่อ่านออกเสียงแน่ใจ
(house-rules → brand name) ไม่แน่ใจ = ใช้ id ที่ไม่ต้องพูดชื่อ.
ถ้อยคำที่เลิกใช้แล้ว (id เดิมถูกเขียนทับ 2026-11-26 ห้ามพูด): game-1 "สายเกม<แนวเกม>ฟังทางนี้…",
game-2 "เบื่อเกมเดิมๆ ที่เล่นยังไงก็จำเจอยู่ไหม?", game-3 "<แนวเกม>ที่เล่นแล้ววางจอยไม่ลง ตัวนี้ต้องมี",
game-4 "ของมันต้องมีสำหรับคนที่รอเกมแนวนี้อยู่".
- **ก่อนค้น ให้สแกน `/opt/data/clips/logs/clip-log.jsonl` หาชื่อเกมเดียวกันก่อน** (อีกแพลตฟอร์ม / อีกรุ่นของเกมที่เคยทำคลิปไว้) — แถว log *อาจ* ทิ้งแนวเกม + วันวางจำหน่าย + ภาษาที่ยืนยันจากแหล่งทางการไว้ใน `notes` (notes ส่วนใหญ่เป็นบันทึกเทคนิคเรื่องเสียง/ซับ ไม่ใช่ข้อมูลเกม จึงไม่ใช่ทุกแถวที่มี) ถ้าแถวของเกมเดิมมีครบก็ใช้ซ้ำและข้าม `web_search` ไปได้ (เกมเดียวกันเพิ่งทำคลิป Switch แล้วมาทำ PS5 = ข้อมูลชุดเดิม ไม่ต้องค้นใหม่); **ถ้าแถวไม่ได้ทิ้งไว้ อย่าสมมติว่ามีใน log — ค้นตามกฎข้างบนหนึ่งครั้ง แล้วใช้ผลค้นนั้น**
- **ค้นแล้วไม่เจอแนว/ข้อมูลเกมเลย** → `game-9` (ใช้แค่ชื่อเกมจากชื่อสินค้า) และอย่าเดาแนวในเสียงพากย์
- **ทิศทาง hook ของฟิกก็เป็น claim เช่นกัน:** ถ้าเขาสั่ง hook แนวนั้นแน่นี้พร้อมระบุ attribute (2D / open-world / co-op / เล่นคนเดียว) ให้ยืนยัน attribute นั้นจากแหล่งเดียวกับที่ค้นแนวเกมก่อนใส่เสียงพากย์ — ผลค้นยืนยัน "แนว" ได้ แต่ไม่ได้ยืนยันทุกอย่างที่ direction บอก, และกับเกม "label สินค้า" คือแหล่งนั้นเอง: ยืนยันไม่ได้ = ตัดคำนั้นทิ้งแล้วคงเจตนาไว้ ไม่ใช่พูดตาม

## เกมเพลย์ / trailer footage (preset `gameplay` — `gph-N`)
**New ids `gph-1`..`gph-10` (2026-11-05).** Do **not** reuse or extend `gameplay-N` — those are old per-clip counters already in `/opt/data/clips/logs/clip-log.jsonl`; from now on log `hook_id:"gph-N"` for gameplay clips. LRU / 5-row rule / same-date tie-break exactly as above, looked up over rows with `style:"gameplay"`.
Placeholders: `<แนวเกม>` (genre from the one `web_search`), `<เกมที่คล้าย>` (a well-known game in the same genre/series — must be a real, obvious comparison; skip the hook if none), `<จำนวนวัน>` (days from post date to release, written as a word for TTS).
**📅 = needs a day-level release date confirmed by two sources** (store page = search result, per gameplay-clips step 1). If only month-level is safe, do NOT pick a 📅 hook — take the next LRU one. All hooks are price-free; never pair them with "ถูก/คุ้ม/ลด" wording.
EN pill = the caption for the hook beat (≤2 words, EN only).

| id | Thai spoken opener | type | EN pill | 📅 |
|---|---|---|---|---|
| `gph-1` | "ถ้าชอบ <เกมที่คล้าย> ตัวนี้ห้ามพลาด" | comparison | `MUST PLAY` | |
| `gph-2` | "อีก <จำนวนวัน> วันได้เล่นแล้ว นับถอยหลังกันเลย" | countdown | `ALMOST HERE` | 📅 |
| `gph-3` | "ฉากนี้แหละ คือเหตุผลที่ต้องพรีฯ" | pattern-interrupt (cut on the best shot) | `THIS SCENE` | |
| `gph-4` | "สาย<แนวเกม>ห้ามเลื่อนผ่าน ดูให้จบก่อน" | callout | `WAIT FOR IT` | |
| `gph-5` | "ใครเล่นฉากนี้ผ่านรอบเดียว ขอคารวะ" | challenge | `TRY THIS` | |
| `gph-6` | "รู้ยัง? เกมนี้ทำได้มากกว่าที่ trailer บอก" | curiosity | `NO WAY` | |
| `gph-7` | "เตรียมเคลียร์ตารางได้เลย <แนวเกม>ตัวนี้มาแน่" | hype | `CLEAR SCHEDULE` | |
| `gph-8` | "หยุดก่อน! ดูช็อตนี้แล้วจะเข้าใจ" | pattern-interrupt | `STOP` | |
| `gph-9` | "เกมที่แก๊งเพื่อนต้องนัดเล่นด้วยกัน" | social | `SQUAD UP` | |
| `gph-10` | "วันที่ <วันวางขาย> นี้ ใครยังไม่พรีฯ ระวังตกขบวน" | FOMO / release date | `DAY ONE` | 📅 |

Notes: `gph-10`'s `<วันวางขาย>` is spoken as words ("สิบห้าพฤศจิกายน"); on the pill use `DAY ONE` or `25 FEB` style (≤2 words), never the full date with year. `gph-1`/`gph-4`/`gph-7` without a confirmed `<เกมที่คล้าย>`/`<แนวเกม>` → choose another id rather than guessing.

## สินค้า — footage จากวิดีโอทางการ (preset `footage` — `pft-N`, added 2026-11-10)
For 🎬 product clips cut from the brand's own film (gameplay-clips `references/product-footage.md`). Pick with
`perf.py pick-hook --category <product category> --prefix pft-`; LRU / 5-row rule as above over rows of that
category. Hooks describe what the footage SHOWS — never a personal-use claim ("ใช้มาหนึ่งสัปดาห์") because
nobody used it, and never price/ถูก/คุ้ม/ลด. Placeholders: `<สินค้า>` = short Thai product noun ("แว่น XR",
"เครื่องซักผ้า"); `<ฟีเจอร์>` = ONE feature stated on the brand page (skip the hook if none).

| id | Thai spoken opener | type | EN pill |
|---|---|---|---|
| `pft-1` | "ดูช็อตนี้ก่อน แล้วจะรู้ว่าทำไมคนพูดถึง<สินค้า>ตัวนี้" | pattern-interrupt (hero shot) | `WATCH THIS` |
| `pft-2` | "<สินค้า>ทำแบบนี้ได้ด้วยเหรอ" | curiosity | `NO WAY` |
| `pft-3` | "ใครกำลังหา<สินค้า>อยู่ ดูตัวนี้ก่อนตัดสินใจ" | callout | `WATCH FIRST` |
| `pft-4` | "<ฟีเจอร์> ฟีเจอร์เดียวที่ทำให้ตัวนี้ไม่เหมือนใคร" | feature | `ONE FEATURE` |
| `pft-5` | "สามอย่างที่<สินค้า>ตัวนี้ทำได้ ดูให้จบ" | list | `TOP 3` |
| `pft-6` | "ดูการทำงานจริงของมันกันเลย" | demo | `SEE IT` |
| `pft-7` | "บ้านไหนยังใช้แบบเดิมอยู่ ลองดูอันนี้" | upgrade | `UPGRADE` |
| `pft-8` | "หน้าตาของจริงเป็นแบบนี้ ไม่ใช่แค่ในรูป" | reveal | `REAL LOOK` |

## อิเล็กทรอนิกส์ / แก็ดเจ็ต (`gadget`)
- `gadget-1` — "ของชิ้นเล็กที่ทำให้โต๊ะทำงานดูแพงขึ้นทันที"
- `gadget-2` — "ใช้มาสักพักแล้ว ขอยอมรับตรงๆ ว่าติด"
- `gadget-3` — "สเปกเทียบกับรุ่นที่คนนิยม ตัวนี้ชนะขาด" *(rewritten 2026-11-05: old text "สเปกเทียบกันในราคาระดับเดียวกัน…" referenced price — house rule: no price/currency/discount spoken, on screen, or implied by the hook. Same id kept so the LRU history stays valid.)*
- `gadget-4` — "อันนี้เล็กแค่ฝ่ามือ แต่ทำได้เยอะเกินคาด"
- `gadget-5` — "ใครยังทำแบบเดิมอยู่ ดูอันนี้ก่อน"
- `gadget-6` — "ของที่ซื้อมาแล้วใช้ทุกวันจริงๆ มีไม่กี่ชิ้น นี่คือหนึ่งในนั้น"

## บ้าน / ครัว / ความสะอาด (`home`)
- `home-1` — "งานบ้านที่เคยเหนื่อย ตอนนี้เหลือแค่กดปุ่มเดียว"
- `home-2` — "ลองใช้มาหนึ่งสัปดาห์ ผลลัพธ์คือ…"
- `home-3` — "มุมไหนของบ้านที่จัดการยากที่สุด? ตัวนี้จัดให้"
- `home-4` — "ห้องรกแค่ไหน ดูก่อนกับหลังใช้ตัวนี้"
- `home-5` — "ทริคเล็กๆ ที่ทำให้บ้านน่าอยู่ขึ้นแบบไม่ต้องรีโนเวท"
- `home-6` — "ใครขี้เกียจทำงานบ้านเหมือนกัน ยกมือ"

## ความงาม / ดูแลตัวเอง (`beauty`)
- `beauty-1` — "อยากหน้าดูสดใส ข้อแรกเลยคือ…" *(rewritten 2026-11-05: old text "…ไม่ต้องพึ่งของแพง…" implied cheapness — price-free rule. Same id kept.)*
- `beauty-2` — "ใช้แทนตัวที่เคยใช้มาหลายขวด สรุปคือเวิร์กกว่า"
- `beauty-3` — "เนื้อสัมผัสแบบนี้ ให้ฟีลแบบนี้ หายากนะ" *(rewritten 2026-11-05: old text "ของในราคาระดับนี้…" referenced price — house rule: no price/currency/discount spoken, on screen, or implied. Same id kept so the LRU history stays valid.)*
- `beauty-4` — "ทาไปครั้งเดียว เพื่อนทักว่าทำอะไรมา"
- `beauty-5` — "สายผิวแพ้ง่ายฟังทางนี้"
- `beauty-6` — "ขั้นตอนเดียวที่เพิ่มเข้ามา แล้วผิวเปลี่ยนเลย"

## เสื้อผ้า / แฟชั่น (`fashion`)
- `fashion-1` — "ชิ้นเดียวแมตช์ได้หลายลุค ลองดู"
- `fashion-2` — "หยิบมาใส่บ่อยที่สุดในสัปดาห์นี้"
- `fashion-3` — "ผ้าดีไซน์โดน แต่ที่สำคัญกว่าคือใส่สบาย"
- `fashion-4` — "ไม่รู้จะใส่อะไร หยิบตัวนี้ไม่เคยพลาด"
- `fashion-5` — "ลุคนี้ใส่ไปไหนก็มีคนถามว่าซื้อที่ไหน"
- `fashion-6` — "ใส่ทั้งวันยังไม่อยากถอด"

## อาหาร / ของกิน (`food`)
- `food-1` — "ของกินตุนไว้ที่บ้าน ไม่เคยเหลือ"
- `food-2` — "ครั้งแรกที่ลอง ครั้งที่สองสั่งซ้ำแล้ว"
- `food-3` — "ของกินเล่นที่ไม่ต้องรู้สึกผิด"
- `food-4` — "เปิดถุงแล้วหยุดไม่ได้ เตือนแล้วนะ"
- `food-5` — "หิวตอนดึกทีไร หยิบอันนี้ตลอด"
- `food-6` — "รสชาติที่ต้องลองเองถึงจะเข้าใจ"

## hook_id selection with performance (when data exists)
Perf numbers live in `/opt/data/clips/logs/perf-log.jsonl` (one row per stats reading, joined to `/opt/data/clips/logs/clip-log.jsonl` by `sha256`) — **never inside clip-log rows**. Details: `references/performance-tracking.md`.
Pick with the script instead of by hand:
`python3 scripts/perf.py pick-hook --category <cat>` (gameplay: `--category game --prefix gph-`, or `--candidates gph-1,gph-3,...` to pass only ids whose 📅/placeholder needs are met).
- It excludes ids used in the last 3 rows of the category, ranks the rest by Bayesian-smoothed CTR (prior 2% over 500 views, so unseen hooks still get explored), and falls back to plain LRU when no perf data exists.
- `orders` is not used for ranking (clicks-per-view is the hook's job; orders depend on the product).
- Record stats only with `perf.py add` when Fix supplies numbers; never edit old clip-log rows.

## Soft CTA (ใช้แทนกันได้ ห้ามมีราคา)
- `cta-1` — "ลิงก์อยู่ใต้คลิปนะจ๊ะ ไปดูรายละเอียดกันได้เลย"
- `cta-2` — "พิกัดอยู่ใต้คลิปจ้า"
- `cta-3` — "สนใจกดดูรายละเอียดที่ลิงก์ใต้คลิปได้เลยนะ"
