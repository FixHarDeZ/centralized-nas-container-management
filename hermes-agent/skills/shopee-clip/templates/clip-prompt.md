# Flow clip prompt template (proven structure — fill the <> parts, keep every section)

> **2026-11-05 override:** Flow must render NO on-screen text. Use the "ON-SCREEN TEXT: NONE" block from `references/presenter-post.md` instead of any caption/pill instruction below. EN pills and Thai subs are added in post by `scripts/post_presenter.py`.


<Pitch sentence in Thai, 1–2 lines: the pain point, then the product as the fix. 9:16 vertical format. A short, cute product review video in 9:16 vertical format.>
The presenter is <Nong Mint / saved character name>, <appearance: young Thai woman, straight black hair and bangs> (attached as an ingredient chip; add `entity_id: <from the Characters picker>` only if you did NOT attach the character), wearing <outfit>. She is reviewing the <product, exact description from the Shopee listing> (attached as ingredient images — say "use the attached product images so the product matches them exactly").

Sequence of actions:
1. <struggle / before-state with the old way — expressive>
2. <close-up of the product doing its job — the money shot>
3. <feature demo: show the key part, look impressed>
4. <wink + points down next to the product — the CTA gesture>

Audio (Thai voiceover — spoken only, NO narration text on screen):
"<hook question> <1–2 highlights in teen slang: ปัง/เริ่ด/ของมันต้องมี/ดี๊ดี> <soft CTA: พิกัดลิงก์ใต้คลิปนะจ๊ะ!>"

> **Fix สั่ง 2026-11-05 (presenter เป็นหลัก, ใช้กับทุกแนว):** ห้ามใส่คำอธิบาย/สไตล์บรรยาย "น่ารักๆ" ในส่วน Audio/ผู้บรรยาย (เช่น "Cute and cheerful female voice", "เสียงพากย์ไทยหญิงน่ารัก", "พรีเซนเตอร์หญิงน่ารัก ยิ้มเก่ง") — Flow มักเอาบรรทัดพวกนี้ไปเขียนเป็นข้อความไทยบนจอแล้วเพี้ยนทุกครั้ง เอาออกหมด เหลือแค่**ประโยคพูดจริง** + `Thai voiceover` เท่านั้น

> **Typing this prompt (step 4):** ONE full-length `cdp('Input.insertText', text=PROMPT)` is fine for a ~2,500–2,900-char prompt — the replace-bug that produced half-length prompts was a clear-then-retype cycle, not insert size. Read back `innerText.length` AND a head/tail slice: the length settles ~38 chars lower once the editor re-renders (innerText normalizes the `\n\n` runs), so a few-dozen-char drift with an intact head/tail is re-rendering, not truncation — judge truncation on the tail, never on the number.

Visual style: Bright, fun social media aesthetic, vibrant rounded fonts popping up on screen (e.g. "<caption 1>", "<caption 2>", "<caption 3>"), consistent with the provided storyboard grid and product references. NO prices or currency symbols should appear.

---
Rules baked in: no price / no Baht figures anywhere (spoken or on-screen); captions per beat, rounded + colorful; soft CTA only ("ลิงก์ใต้คลิป"), never a hard sell; ~10 s single scene is enough.
Stray-prop prohibition — add whenever the project has held OTHER products' props: the model pulls an earlier clip's props into this one (a previous controller clip put a controller on the table of a box-only brief), so name the single product plus everything else allowed in frame, e.g. `ในเฟรมมีแค่กล่องเกมนี้เท่านั้น ห้ามมีจอย / ตัวควบคุม / อุปกรณ์อื่นบนโต๊ะ`, then verify it in the frame check (step 10).
Multi-scene hard rule (Fix 2026-10-27): when the clip is longer than one generation, EVERY scene except the last must carry NO link/CTA wording at all — put this line verbatim in each non-final scene prompt: `ห้ามมีคำว่า ลิงก์ / ใต้คลิป / คำอธิบาย / พิกัด ใดๆ ใน scene นี้ ทั้งพูดและขึ้นบนจอ — CTA อยู่เฉพาะส่วนที่ 2 เท่านั้น`. Then verify it in the frame check (last ~1 s of the non-final scene) and re-gen the scene if a link caption still shows.
Physical counts (drawers, doors, knobs, shelves) go into the prompt as exact numbers with a 'no extra X' clause, e.g. `exactly three drawers, no fourth drawer` — an unstated count lets the model add parts the product does not have. Scale goes in the same way: real dimensions PLUS a body anchor (`a SMALL LOW cabinet, ~70–90 cm — its roof reaches only her HIP when she stands beside it; never chest-height, never a built-in wall unit`), because the model defaults to filling the frame with the product — the no-size rule bans cm from VO/on-screen only, never from the prompt. Verify the anchor in the frame check (product top vs presenter body part).
When a storyboard grid exists in the project, mention "consistent with the provided storyboard grid" so the clip matches the frames.

## Variant: mechanism-driven products (pest control, cleaners, repair gels)
When the product's invisible action IS the selling point (bait that spreads through a nest, a cleaner that lifts a stain), scene 3 cannot be a normal "show the feature" demo — make it an explicit SIMULATION beat: "a cutaway showing the effect spreading" (มดกินแล้วเอาไปแบ่งทั้งรัง → ออกฤทธิ์แบบโดมิโนลามถึงทั้งรัง). Name the mechanism word on-screen ("โดมิโนเอฟเฟกต์") as a caption. Add the product's trust facts (สูตรใหม่จากเยอรมนี, ไร้กลิ่น ไม่มีสี, ใช้ได้ทุกบริเวณ) as a จุดเด่น line rather than spending a scene on them.

## Variant: multiple product photos
If Fix sends several photos, pick 2–3 that cover (a) the product held/in use as the hero, (b) the problem it solves, (c) the mechanism or application shot. Attaching all 10 of 10 rarely helps and each attach is a picker round-trip.

## Variant: คลิปแผ่นเกม / ตลับเกม (Fix สั่ง 2026-10-28)
- **Hook และเสียงพากย์ต้องพูดถึง "ตัวเกม"**: แนวเกม + จุดขาย 1 ข้อ (เนื้อเรื่อง / เกมเพลย์ / ระบบการเล่น) เช่น `"RPG แฟนตาซี เนื้อเรื่องยาว เล่นเป็นอาทิตย์ยังไม่จบ"` — ดึงจาก `web_search` ชื่อเกม + publisher/แพลตฟอร์มทางการ (หนึ่งครั้งพอ; ลิสติ้ง Shopee อ่านไม่ได้เพราะ WAF จึงใช้เป็นแหล่งข้อมูลไม่ได้) ซึ่งให้ทั้งแนวเกม, จุดขาย, วันวางจำหน่าย และภาษาที่รองรับ
- **ห้ามพูดแนวนี้**: "วางบนชั้นแล้วเพื่อนทักทุกครั้งที่มาบ้าน" / "มีแผ่นเกมแล้วเพื่อนถาม" / ขายความ "มีไว้อวดชั้น" ทุกรูปแบบ — เลิกใช้แล้ว ให้ขายตัวเกมตรงๆ
- ไม่แน่ใจแนวเกมจริงๆ → ใช้ hook กลาง `game-2` และอย่าเดาแนวในเสียงพากย์
- คงกติกาเดิมทุกข้อ: ไม่มีราคา/สกุลเงินใดๆ, วันที่ (เช่น รีสต็อก / วันวางจำหน่าย) พูดได้, CTA นุ่มนวลเฉพาะท้ายคลิป

### Cover-fidelity block (paste verbatim when the clip shows a printed box/case cover)
Flow ไม่เคยก๊อปปี้พิกเซล — มัน re-draw ปกใหม่จาก reference เสมอ จึงต้องสั่งห้ามมัน redesign และให้ crop ปกกล่องกินพื้นที่ ≥ 60% ของภาพอ้างอิง (ครอปกล่องเดียวเต็มเฟรมแนวตั้ง; สินค้า 2 กล่อง = 2 crop แล้วบอกใน prompt ว่ามือไหนถือกล่องไหน) — ถ้า crop ปกเล็ก ปกจะเพี้ยนและแก้ด้วย prompt ไม่ได้:
`reproduce the printed cover art EXACTLY as in the attached image: <รายละเอียดสำคัญของปก เช่น ตัวละคร/ฉาก/ตัวหนังสือ/แถบสีหัวกล่อง>. Do NOT redesign, do NOT change the characters, layout or colors, do NOT swap in different artwork.`

### Caption legibility block (Thai on-screen text garbles on Omni 1.1 Flash)
ใส่ทุกครั้ง ไม่ใช่แค่คลิปเกม — model ขีดเขียนสระ/วรรณยุกต์ไทยไม่ได้ จึงต้องสั่ง caption ให้สั้น:
`CAPTION RULE (สำคัญมาก): ห้ามขึ้นตัวหนังสือภาษาไทยบนจอใดๆ ทั้งสิ้น — ให้ caption บนจอเป็นภาษาอังกฤษ/คำยืมเท่านั้น ไม่เกิน 2 คำต่อ beat (เช่น LEGO Harry Potter / 2 games in 1 / Pre-order 5 Nov / Link below!) วันที่ก็เขียนอังกฤษ เสียงพากย์ไทยคงไว้ตามเดิม`
(Fix ตัดสิน 2026-10-30: mitigation (2) = EN caption กลายเป็น DEFAULT ทุกคลิป — ไทยสั้น 2 คำบนจอยังเพี้ยนซ้ำ และ agent มัก rewrite เพิ่มประโยคไทยยาวขึ้นจอเอง จึงสั่งห้ามไทยบนจอเด็ดขาดแทน) — เดิมใช้คู่กับ caption อังกฤษ/คำยืมใน beat ที่ไม่ใช่วันที่ แล้วคงเสียงพากย์ไทยไว้

## Variant: tech hardware with diagram / cutaway photos
When Fix sends exploded-view or feature-diagram images (sensor cutaways, connection-mode charts, button-mapping screenshots), do NOT spend a scene narrating the diagram — fold them into scene 3 as the reference for the close-up demo, and lift the diagram's own headline into a caption in the tech's words ("จอย Hall Effect ไม่มีดริฟ!", "ปุ่มหลัง map ได้"). List each attached image in the prompt BY ITS ROLE ("the main controller shot, the Hall Effect cutaway, the feature close-ups, the connection-mode diagram") so the model maps beats to the right reference instead of guessing.