# news-feed — Modern Dashboard Design

วันที่: 2026-10-08 (Asia/Bangkok)
สถานะ: ผู้ใช้อนุมัติ Modern Editorial และให้เริ่ม implementation แล้ว (2026-10-08)

## เป้าหมาย

ปรับ dashboard ให้ modern อ่านข่าวภาษาไทยง่าย และเข้าถึงข่าว ราคาโมเดล และสถานะระบบได้เร็ว ทั้ง desktop และมือถือ โดยใช้ FastAPI + vanilla JavaScript เดิม

## สิ่งที่พบจากโค้ด

- Desktop เปิด Source Health เป็นหน้าแรก ขณะที่มือถือเปิด News Timeline
- มี 6 ส่วน: Source Health, News Timeline, AI Price Tracker, Leaderboard, Digest History, Schedule Config
- News Timeline โหลดข่าวล่าสุดสูงสุด 100 รายการ; ตัวกรองปัจจุบันมี search/source/sort
- การโหลดข่าวยังไม่มี error/retry UI และการ refresh รีเซ็ตบางตัวกรอง
- Article title/summary/source ถูกใส่ใน HTML โดยยังไม่ escape ครบ
- Watchlist sync กับ server แล้ว; memory เดิมบางจุดยังระบุว่าเป็น localStorage อย่างเดียว
- คะแนน Intelligence และรายชื่อ Top Hit เป็น reference ที่ฝังใน JavaScript ไม่ใช่อันดับสด
- API มีข้อมูล health, จำนวนข่าวต่อ source ใน 24h, digest schedule/history และ watchlist ที่นำมาแสดงในหน้าสรุปได้

## ทางเลือก

| แนว | ลักษณะ | ข้อแลกเปลี่ยน |
|---|---|---|
| **Modern Editorial — แนะนำ** | พื้น off-white, sidebar slate, accent teal, ข่าวเป็นจุดหลัก | เหมาะกับอ่านสรุปไทยยาวและใช้งานทุกวัน |
| Dark Workspace | พื้น charcoal, accent cyan, ตารางข้อมูลเด่น | เหมาะกับดูราคา/สถานะในที่แสงน้อย แต่ให้บรรยากาศหน้าควบคุมมากกว่าอ่านข่าว |
| Bento Overview | หน้าแรกเป็น grid ของข่าว/ราคา/สถานะ | เห็นหลายเรื่องพร้อมกัน แต่เพิ่มหน้าและขั้นตอนก่อนอ่านข่าว |

รายละเอียดต่อไปนี้เป็นแบบ Modern Editorial

## รูปแบบและลำดับข้อมูล

- Desktop: sidebar กว้างประมาณ 220px, เนื้อหาสูงสุดประมาณ 1320px, แบ่งเมนูเป็นอ่านข่าว/โมเดล/ระบบ
- Tablet: sidebar ย่อหรือเปลี่ยนเป็นแถบเมนูตามพื้นที่จริง ไม่ปล่อยตารางเบียดเนื้อหา
- Mobile: bottom navigation ข่าว/ราคา/อันดับ/เพิ่มเติม, drawer สำหรับประวัติ digest/แหล่งข่าว/ตั้งค่า; รองรับ safe-area
- เปิด News Timeline เป็นหน้าแรกทั้ง desktop และ mobile
- Header ของแต่ละหน้าแสดงชื่อ คำอธิบายสั้น และ action ที่เกี่ยวข้อง
- ใช้ inline SVG สำหรับไอคอนหลัก, system fonts ที่รองรับไทย, spacing สม่ำเสมอ, contrast อ่านชัด, focus ring
- ใช้ accent teal สำหรับ action/selected state; สี amber/red/green ใช้เฉพาะสถานะที่ต้องสื่อความหมาย
- การเคลื่อนไหวสั้นและเคารพ prefers-reduced-motion

```text
Desktop
┌───────────────┬───────────────────────────────────────────────┐
│ NEWS FEED     │ ข่าวและความเคลื่อนไหว                 อัปเดต │
│               │ สรุปข่าว AI & IT เป็นภาษาไทย                 │
│ ข่าวล่าสุด    ├───────────┬────────────┬──────────┬─────────────┤
│ ราคาโมเดล     │ ข่าว 24h  │ แหล่งข่าว │ Digest   │ Watchlist   │
│ อันดับโมเดล   ├───────────┴────────────┴──────────┴─────────────┤
│               │ ค้นหา · แหล่งข่าว · เรียง · ดึงข่าวทันที     │
│ ประวัติ digest│ ทั้งหมด / มีสรุป / ส่งแล้ว     พบ N รายการ   │
│ แหล่งข่าว     ├───────────────────────────────┬───────────────┤
│ ตั้งค่า       │ รายการข่าว + summary preview  │ สถานะล่าสุด  │
│               │ กดขยายสรุป / อ่านต้นฉบับ     │ รอบส่งถัดไป  │
└───────────────┴───────────────────────────────┴───────────────┘
```

## News Timeline และ enhancement ในรอบนี้

1. Summary tiles: ข่าวทั้งหมดใน 24h จาก aggregate source endpoint, แหล่งข่าวที่มีรายการใน 24h, รอบ digest ถัดไป, จำนวน watchlist
2. ข่าวเป็นรายการอ่านง่าย: source, วันเวลา, title, preview สรุปไทยประมาณ 2 บรรทัด, ขยายอ่านเต็ม และลิงก์ต้นฉบับแยกชัด
3. เพิ่ม quick filter ทั้งหมด / มีสรุป / ส่งแล้ว; แสดงจำนวนผลลัพธ์และบอกว่าค้นหาในข่าวล่าสุดสูงสุด 100 รายการ
4. เก็บ search/source/status/sort ระหว่าง refresh ใน session; ไม่บอกว่าเป็น global count เมื่อคำนวณจากข่าวที่โหลดมา
5. Sidebar ข้อมูลในหน้า News แสดง last fetch, digest ล่าสุด และรอบส่งถัดไป; มือถือวางไว้ใต้รายการหรือเป็นการ์ดกะทัดรัด
6. Loading skeleton, empty state และ error พร้อม Retry; แยก API failure ออกจากข้อมูลว่าง และไม่แสดงค่าล้มเหลวเป็นศูนย์
7. Escape ข้อมูลข่าวทั้งหมด, รับลิงก์เฉพาะ http/https และใส่ rel="noopener noreferrer"; ใช้ปุ่มที่เข้าถึงด้วยคีย์บอร์ดสำหรับ expand

จำนวน source ที่มีข่าวใน 24h **ไม่เท่ากับ health check ของ RSS**; ใช้คำว่า "มีข่าวใน 24h" และไม่แสดง source เงียบว่าเสีย

รอบ digest ถัดไปคำนวณจาก digest_times โดยใช้ Asia/Bangkok เสมอ แม้ browser อยู่ timezone อื่น; ถ้าไม่มีเวลาให้แสดงว่ายังไม่ได้ตั้ง

## อีก 5 หน้าร่วมดีไซน์เดียวกัน

- Prices: toolbar และ filter chips สม่ำเสมอ, watchlist card เด่น, table อยู่ใน scroll container, ชื่อโมเดล/ราคาเด่น, copy/star/history ใช้งานเดิม
- Leaderboard: grid 2 คอลัมน์บนจอใหญ่, 1 คอลัมน์บนมือถือ, ปรับหัวการ์ดและ jump links; แสดงชัดว่า Intelligence เป็น reference ในแอปและไม่ได้อัปเดตสด
- Digest History: สถานะและเวลาเด่น, accordion เปิดอ่านง่าย, ปุ่มส่ง Test Digest มีข้อความชัดว่าจะส่งจริง
- Source Health: กราฟและ source rows ใช้สีและ spacing ใหม่; ข้อความสะท้อนจำนวนข่าว ไม่อ้างว่าวัดสุขภาพ feed จริง
- Settings: แบ่ง scheduling/sources/summarizer/retention เป็นกลุ่ม, label ชัด, save action มองเห็นง่าย, danger zone แยกด้านล่างและคง confirmation เดิม

## ขอบเขต implementation

- แก้ `news-feed/app/static/index.html` และ `app.js`; แยก stylesheet เป็น `dashboard.css` เพื่อให้ดูแล tokens/responsive styles ง่าย
- ใช้ API เดิม ไม่เปลี่ยน schema, scheduler, summarizer, notification transport, secrets หรือพอร์ต
- ไม่เพิ่ม framework, build pipeline, remote font หรือ dependency ใหม่
- โหลด summary data แบบแยก failure ต่อ endpoint; reuse ข้อมูลใน session เมื่อเหมาะสม
- เก็บ feature เดิมทั้ง 6 ส่วน รวม custom sources, fallback chain, price expiry, watchlist และ price history

## Verification

- ตรวจ JavaScript syntax และรัน pytest ของ news-feed เพื่อจับ regression ของ API/config เดิม
- ตรวจ dashboard ใน browser ที่ desktop, tablet และ mobile รวม overflow, active navigation, drawer, summary expand, filter และ error/retry
- ตรวจฟีเจอร์เดิม: search/sort/zone, copy model ID, watchlist, price history, digest history และการโหลด settings
- ใช้ mock API หรือ local fixture สำหรับ preview โดยไม่เรียก fetch/digest/send จริง และไม่อ่าน production secrets
- ตรวจ markup ที่มาจาก title/summary/source และ URL ผิดรูปแบบด้วย fixture เพื่อยืนยันว่าไม่ execute HTML
- ตรวจ `git diff --check`; บันทึกผลจริงใน `news-feed/.notes/` ก่อนส่งมอบ

## ข้อเสนอ enhance รอบถัดไป

- Bookmark/อ่านแล้วสำหรับข่าว พร้อม sync ข้ามอุปกรณ์: ต้องเพิ่ม backend state และ API
- Pagination หรือโหลดเพิ่ม: ค้นหาและอ่านเกิน 100 ข่าวล่าสุดได้
- Model comparison: เลือก 2–3 โมเดลมาเทียบราคา/context และประมาณค่าใช้จ่ายจาก token usage
- Benchmark source ที่อัปเดตได้ พร้อมวันที่/ลิงก์อ้างอิง: แทนคะแนน Intelligence ที่ฝังไว้
- สถานะ RSS/summarizer จริง: last success/error ต่อ source และ backlog summary เพื่อวินิจฉัยปัญหาได้ตรงกว่า article count

## การส่งมอบ

ผู้ใช้อนุมัติแบบและ implementation แล้ว: ปรับครบ 6 หน้า พร้อม overview, filters, error/retry, safe rendering และ async guards. ตรวจผ่าน 133 pytest + 22 Node tests, JavaScript syntax, static hooks และ FastAPI static asset routing.

Implementation commit `77e5481` push แล้ว; merge main release `56354a5` และ deploy เฉพาะ news-feed บน NAS สำเร็จ. Post-deploy app healthy, API/assets 200 และ SHA-256 ของทั้ง 4 static assets ตรง release; Nginx basic auth ยังคง 401 เมื่อไม่มี credentials.

Browser preview ถูกปฏิเสธสิทธิ์ จึงยังไม่ยืนยันหน้าตาและ interactions ใน browser จริง. สถานะ release และข้อจำกัดบันทึกใน `news-feed/.notes/daily_log.md` และ `00_INDEX.md`.
