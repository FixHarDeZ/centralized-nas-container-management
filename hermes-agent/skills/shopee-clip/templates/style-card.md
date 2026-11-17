# Fixed style card — append to EVERY clip prompt (the "looks like a series" layer)

> **Text-free since 2026-11-16.** The block used to describe caption fonts, a caption position, "EN labels per
> beat" and `Link below!`. It sat in the same prompt as "ON-SCREEN TEXT: NONE", and on hatari-s14m1 shot 2 Flow
> drew exactly those: pastel rounded pills in the top half (`EASY ADJUST`, `3 LEVELS`, `LINK BELOW!`). A prompt
> sent to Flow names NO caption, label, pill, font or CTA wording anywhere. EN pills, Thai subs and the CTA are
> added in post by `scripts/post_presenter.py`; their look is in `references/presenter-graphics.md`.

Purpose: keep the feed visually consistent across products so clips read as one channel. Copy the block below
into step 7's prompt, AFTER the beat list and BEFORE the voiceover line, unchanged. Before `pack` or a submit,
check the finished `shot<K>.txt`: apart from the "ON-SCREEN TEXT: NONE" block it must not contain the words
caption, label, pill, ป้าย, font, ฟอนต์, subtitle or `Link below`.

Scanning it: cut the block out from `ON-SCREEN TEXT: NONE` through the end of the `ห้ามมีตัวอักษรใดๆ … ทีหลังเอง`
line before grepping — the block itself contains `ป้าย`, so scanning the raw file always false-positives on it.
A hit in the product prose (`a green-and-white label printed …`) is still a hit: the gate is word-based, not
intent-based, so reword the prose (`the green-and-white printed front reading …`) instead of exempting it.
Two words is the whole fix; do not shorten or drop the ON-SCREEN block to make the scan pass.

## The block (Thai, ready to paste)

```
การ์ดสไตล์ (ใช้คงที่ทุกคลิป ห้ามเปลี่ยน):
- โทนภาพสว่างสดใส แสงนุ่ม — ฉาก พื้นหลัง และแสง เหมือนกันทุกช็อตของคลิปเดียวกัน
- จังหวะคลิป: เปิดด้วยท่าดึงสายตา (0-2 วิ) → โชว์จุดเด่น 1-2 ข้อ → ท่าชี้ลง + ยิ้มขยิบตาตอนจบ
- ภาพทั้งคลิปสะอาด ไม่มีตัวอักษรหรือกราฟิกใดๆ ซ้อนบนภาพ (ตัวหนังสือที่พิมพ์อยู่บนตัวสินค้าเองไม่นับ)
- ห้ามมีในภาพ: ราคา, สกุลเงิน, % ส่วนลด, คูปอง, บาร์โค้ด, โลโก้ร้าน, ชื่อร้าน — QR ที่พิมพ์มากับตัวสินค้าเอง (เช่น บนแถบ key-card ของกล่องเกม) ไม่นับเป็นข้อห้าม
- ผู้บรรยาย: พูดเป็นกันเอง ไม่ hard-sell ไม่ตะโกน
```

Notes
- **No shop watermark — Fix's standing call (2026-10-26):** never put a shop name,
  wordmark or "ร้าน" label on screen in any clip, and never ask him for the shop
  name. (The `IMMERZIV` mark on his ad graphic is not a watermark slot.)
- Never put a Baht figure, a discount %, or a crossed-out price in this card —
  the no-price HARD RULE covers on-screen text, not only the voiceover.
- The card is style, not product: product-specific lines (model, region, feature)
  stay in the beat list above it.
