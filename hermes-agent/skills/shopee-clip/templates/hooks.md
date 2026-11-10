# Hook rotation — vary the opener per clip without inventing one each time

Pick ONE hook per clip by category, choosing the LEAST-RECENTLY-USED entry of
that category in `/opt/data/clips/logs/clip-log.jsonl` (look at `hook_id` of the last few rows
with the same `category`). Write the chosen `hook_id` into the log row.

Rule: never reuse a `hook_id` for the same category within 5 consecutive rows.

**Same-date ties break on FILE ORDER.** The log records a date, not a time, so when every candidate's most recent use carries the same `date`, LRU picks the id whose last row sits EARLIEST in the file — that is the least-recently-used one, and the wording tie-break below only applies after that.

**A category with ≤5 hooks makes that rule unsatisfiable** (`game` has 4), so every
candidate technically violates it — do not stall or invent a new id. Parse the log
for that category, take the id whose most recent use is the OLDEST (LRU decides
alone), record it, and move on. Only when the LRU id is wrong for the product does
a tie-break matter: prefer the id whose wording the product actually fits.

## เกม / ตลับเกม (`game`)
**กติกาใหม่ของ Fix (2026-10-28): คลิปแผ่นเกมห้ามใช้ hook/เสียงพากย์แนวนี้ "วางบนชั้นแล้วเพื่อนทักทุกครั้งที่มาบ้าน"** (ใช้ไปแล้วในคลิป FINAL FANTASY RESONANCE — เขาสั่งเลิกเด็ดขาด) ให้ hook + voiceover พูดถึง **ตัวเกม** แทน: แนวเกม (RPG / แอคชัน / ผจญภัย / สยองขวัญ / ไฟต์เตอร์ / แข่งรถ / จำลองสถานการณ์), เนื้อเรื่อง, เกมเพลย์ หรือระบบการเล่น — แนวเกมนั้น **หาจาก `web_search` ครั้งเดียว** (ชื่อเกม + publisher/แพลตฟอร์มทางการ): ลิสติ้ง Shopee อ่านไม่ได้เพราะ WAF จึงเป็นแหล่งข้อมูลที่ใช้ไม่ได้จริง, และผลค้นหาทางการยืนยันได้ทั้ง แนวเกม + วันวางจำหน่าย (ใช้เป็นวันที่ในคลิปได้) + ภาษาที่รองรับ (ใช้ยืนยัน region/language ที่ Fix ส่งมา) แล้วเติมลง `<แนวเกม>` ใน hook ที่เป็น template — **ค้นครั้งแรกให้ใช้ภาษาของ publisher ด้วย**: query ชื่อเกมภาษาอังกฤษล้วนคืนผลว่างได้จริงสำหรับเกมที่ marketing ญี่ปุ่น (เช่น FINAL FANTASY RESONANCE ค้นอังกฤษได้ 0 รายการ แต่ `ชื่อเกม + スクウェア・エニックス + 発売日` ได้ press release ทางการทันที) ซึ่งให้ แนวเกม (ジャンル) + วันวางจำหน่าย + ตาราง対応言語 ที่ยืนยัน region/language ของตลับที่ Fix ส่งมา — ถ้า query แรกคืนว่าง ให้สลับภาษาอีกครั้งเดียวแล้วหยุด อย่าวนลูป
- `game-1` — "สายเกม<แนวเกม>ฟังทางนี้…" (แทนที่ "แอคชันซูเปอร์ฮีโร่" ด้วยแนวจริงของเกมนั้น)
- `game-2` — "เบื่อเกมเดิมๆ ที่เล่นยังไงก็จำเจอยู่ไหม?" (hook กลาง ไม่แตะชั้นวาง ไม่แตะเพื่อน)
- `game-3` — "<แนวเกม>ที่เล่นแล้ววางจอยไม่ลง ตัวนี้ต้องมี" (id เดิม เนื้อหาใหม่ — แทน hook "เพื่อนทักทุกครั้ง" ที่ถูกยกเลิก)
- `game-4` — "ของมันต้องมีสำหรับคนที่รอเกมแนวนี้อยู่"
- **ก่อนค้น ให้สแกน `/opt/data/clips/logs/clip-log.jsonl` หาชื่อเกมเดียวกันก่อน** (อีกแพลตฟอร์ม / อีกรุ่นของเกมที่เคยทำคลิปไว้) — แถว log มีแนวเกม + วันวางจำหน่าย + ภาษาที่ยืนยันจากแหล่งทางการติดไว้แล้ว ใช้ซ้ำได้เลยและข้าม `web_search` ไปได้ (เกมเดียวกันเพิ่งทำคลิป Switch แล้วมาทำ PS5 = ข้อมูลชุดเดียวกัน ไม่ต้องค้นใหม่)
- **ถ้าไม่แน่ใจว่าเกมเป็นแนวไหน** ให้ `web_search` ชื่อเกมก่อน (หนึ่งครั้งพอ) — ถ้ายังไม่มีแหล่งยืนยันแนว อย่าเดา ใช้ hook กลาง `game-2` แล้วเว้นการอ้างแนวเกมในเสียงพากย์ไว้ 1 จุดแทน

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
