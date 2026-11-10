# Fixed style card — append to EVERY clip prompt (the "looks like a series" layer)

> **2026-11-05 override:** Flow must render NO on-screen text. Use the "ON-SCREEN TEXT: NONE" block from `references/presenter-post.md` instead of any caption/pill instruction below. EN pills and Thai subs are added in post by `scripts/post_presenter.py`.


Purpose: keep the feed visually consistent across products so clips read as one
channel, instead of re-inventing tone per prompt. Copy the block below into
step 4's prompt, AFTER the beat list and BEFORE the voiceover line, and swap
only the caption words (they come from `hooks.md` / the product).

## The block (Thai, ready to paste)

```
การ์ดสไตล์ (ใช้คงที่ทุกคลิป ห้ามเปลี่ยน):
- โทนภาพสว่างสดใส แสงนุ่มแบบสตูดิโอ พื้นหลังสะอาดตา
- ฟอนต์ caption ทรงกลม มุมมน สีพาสเทลตัดกับพื้นหลัง เด้งขึ้นมาทีละช็อต ไม่เกิน 3 บรรทัดพร้อมกัน — แต่ละบรรทัดสั้นที่สุด ไม่เกิน 2 คำ — **ห้ามมีอักขระภาษาไทยบนจอแม้แต่ตัวเดียว (Fix สั่ง 2026-11-02: "คำภาษาไทยในคลิปชอบเพี้ยน ไม่ใช้ภาษาไทยในตัวอักษรในคลิปเลย" = zero Thai glyphs on screen, มีผลทุกคลิปตั้งแต่ 2026-11-03)** — ใช้ EN/คำยืมล้วน (วันที่ก็ EN เช่น `5 Nov` / `4 Mar`; CTA = `Link below!`) เสียงพากย์ไทยคงไว้ตามเดิม
- ตำแหน่ง caption: ล็อกครึ่งบนของจอ ไม่บังสินค้า ไม่ชนขอบ 9:16
- จังหวะคลิป: hook (0-2 วิ) → จุดเด่น 1-2 ข้อ → ท่าชี้ลง + ยิ้มขยิบตา (CTA)
- ห้ามมี: ราคา, สกุลเงิน, % ส่วนลด, คูปอง, บาร์โค้ด, โลโก้ร้านขนาดใหญ่, ชื่อร้าน/watermark ร้าน — QR ที่พิมพ์มากับตัวสินค้าเอง (เช่น บนแถบ key-card ของกล่องเกม) ไม่นับเป็นข้อห้าม
- ผู้บรรยาย: ไม่ hard-sell ไม่ตะโกน — **ห้ามใส่ "คำอธิบาย/สไตล์บรรยาย น่ารักๆ" ลงในพรอมป์ผู้บรรยายเด็ดขาด (Fix สั่ง 2026-11-05: *\"ปรับใหม่ กรณี gen แบบ presenter ไม่ต้องมีคำอธิบายน่ารักๆในคลิปแล้ว เพราะ Flow ชอบแหกกฏใส่มาให้ แล้วภาษาไทยเพี้ยนตลอด เอาออกไปเลย\"*)**
- ข้อความบนจอ: มี "เฉพาะ" ป้าย EN สั้นตาม beat เท่านั้น — ห้ามมีคำบรรยาย/ประโยคบรรยาย/คำอธิบายเพิ่มเติมใดๆ (ไม่ใช่แค่ภาษาไทย: ประโยคยาวภาษาอังกฤษบรรยายสินค้าก็ห้ามขึ้นจอ)
```

Notes
- **No shop watermark — Fix's standing call (2026-10-26):** never put a shop name,
  wordmark or "ร้าน" label on screen in any clip, and never ask him for the shop
  name. (The `IMMERZIV` mark on his ad graphic is not a watermark slot.)
- Never put a Baht figure, a discount %, or a crossed-out price in this card —
  the no-price HARD RULE covers on-screen text, not only the voiceover.
- The card is style, not product: product-specific lines (model, region, feature)
  stay in the beat list above it.
