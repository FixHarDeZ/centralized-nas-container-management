# Hashtag pools by category — mix 4 product + 3 vibe + 1 platform tag

Gate BEFORE delivery (unchanged, hard):
- `len(tag_string) <= 150` including spaces
- zero CJK/full-width codepoints:
  `any(0x4E00<=ord(c)<=0x9FFF or 0x3400<=ord(c)<=0x4DBF or 0xF900<=ord(c)<=0xFAFF or 0x3000<=ord(c)<=0x303F or 0xFF00<=ord(c)<=0xFFEF for c in tag_string)`
- no price-flavoured tags: #ราคาถูก #ลดราคา #โปร #คุ้มราคา — the no-price rule
  extends to tags
- vary the set per clip so posts never look duplicated (drop the weakest tag to
  fit the 150-char gate)

**Picking `game` vs `gadget` for gaming products:** content (cartridge / key / title) → `game`; hardware you hold or plug in (controller, handheld, dock, shelf, capture card) → `gadget` — every hardware clip in the log sits under `gadget`, and the category drives BOTH this pool and the hook LRU in `hooks.md`, so guessing wrong changes two things at once.

## `game` (ตลับเกม / คอนโซล)
product pool: draw 4 product nouns from the product's OWN title / platform / genre — the pool is a vocabulary, not a fixed list. LEGO Batman: `#LEGOBatman #แบทแมน #TTGames #WarnerBros #NintendoSwitch2 #Switch2 #เกมตลับ #เกมส์ตลับ`; a PS5 title: `#PS5 #UntilDawn2 #เกมPS5 #เกมสยองขวัญ #XboxSeries #เกมแอคชัน #เกมผจญภัย`
vibe pool: `#ของมันต้องมี #รีวิวของดี #ของดีบอกต่อ #เกมเมอร์ #สายเกม`
platform: `#ShopeeTH`

## `gadget` (อิเล็กทรอนิกส์ / แก็ดเจ็ต)
product pool: `#แก็ดเจ็ต #ของมันต้องมีโต๊ะทำงาน #อุปกรณ์ไอที #รีวิวแก็ดเจ็ต #เทคโนโลยี` + brand/model tag
vibe pool: `#ของดีบอกต่อ #ของมันต้องมี #ดีไซน์มินิมอล #รีวิวของดี`
platform: `#ShopeeTH`

## `home` (บ้าน / ครัว)
product pool: `#ของใช้ในบ้าน #ของมันต้องมี #เครื่องใช้ไฟฟ้า #ตัวช่วยแม่บ้าน #ของดีบอกต่อ` + brand tag
vibe pool: `#ดีไซน์มินิมอล #บ้านและสวน #รีวิวของดี #ของดีบอกต่อ`
platform: `#ShopeeTH`

## `beauty` (ความงาม)
product pool: `#_skincare #ของมันต้องมี #รีวิวความงาม #ของดีบอกต่อ` + brand tag
vibe pool: `#ดูแลตัวเอง #รีวิวของดี #ของดีบอกต่อ #หน้าเด็ก`
platform: `#ShopeeTH`

## `fashion` (เสื้อผ้า)
product pool: `#แฟชั่น #เสื้อผ้า #ของมันต้องมี #แมตช์ลุค` + brand tag
vibe pool: `#ดีไซน์มินิมอล #ของดีบอกต่อ #รีวิวของดี`
platform: `#ShopeeTH`

## `food` (อาหาร / ของกิน)
product pool: `#ของกิน #ของมันต้องมี #รีวิวของกิน #ของดีบอกต่อ` + brand tag
vibe pool: `#ของกินเล่น #รีวิวของดี #ของดีบอกต่อ`
platform: `#ShopeeTH`
