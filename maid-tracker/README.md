# Maid Tracker

ระบบบันทึกการทำงานและเงินเดือนแม่บ้าน — Single-Page Application ที่รันบน Docker

![Maid Tracker](../screenshots/maid-tracker.png)

## Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI (Python 3.12) |
| Database | SQLite (persisted ใน named volume) |
| Frontend | Vanilla JS + Bootstrap 5 (SPA, hash-based routing) |
| Port | 5055 → container 8000 |

## Features

### 👤 จัดการข้อมูลแม่บ้าน
- เพิ่ม / แก้ไข / ลบข้อมูล (ชื่อ, อายุ, สัญชาติ, เบอร์โทร, LINE, Facebook)
- เงินเดือน + วันเริ่มงาน + แสดงระยะเวลาทำงาน

### 📅 ปฏิทินการทำงาน
- คลิกวันเพื่อเปลี่ยนสถานะ พร้อม **confirmation dialog** ก่อนบันทึกลา/ชดเชย
- สถานะ: **ทำงาน**, **ลา**, **หยุด** (อาทิตย์), **ชดเชย** (ทำอาทิตย์)
- บันทึกเหตุผลการลาในแต่ละวัน
- เดินหน้า-หลังเดือนได้

### 📋 บันทึกวันลา
- รายการวันลาในเดือนแสดงใต้ปฏิทิน
- คลิกปฏิทินวันลา → กลับเป็นทำงาน/หยุดได้ทันที (พร้อม confirm)
- แก้ไขเหตุผลการลาแต่ละวัน

### 📊 สรุปรายเดือน
- นับวันทำงาน / ลา / หยุด / ชดเชย
- คำนวณอัตราค่าจ้างรายวัน (เงินเดือน ÷ วันทำงาน Mon–Sat ในเดือน)
- ฐานเงินเดือน (pro-rate เดือนแรกถ้าเริ่มงานกลางเดือน)
- แสดงยอดลา/ชดเชยสะสม — **ไม่หักเงินเดือนรายเดือน** (ดูนโยบายด้านล่าง)
- ยอดยกมาจากเดือนก่อน + ยอดสะสมรวม

### 💰 ระบบจ่ายเงินเดือน
- แบ่งจ่าย **2 รอบ/เดือน**: รอบแรก (วันที่ 15) และรอบสอง (วันสุดท้ายเดือน)
- แต่ละรอบ = เงินเดือน ÷ 2 (ไม่มีการหักลา/ชดเชยรายเดือน)
- กดบันทึกว่าจ่ายแล้ว / ยกเลิก พร้อมแสดงเวลาที่จ่าย
- แสดง alert แจ้งรอบที่ยังค้างจ่าย

### 🚪 ระบบลาออก
- บันทึกวันที่ลาออก + เหตุผล
- สรุปการลาออก: เงินเดือนเดือนสุดท้าย (pro-rate) ± ยอดสะสมลา/ชดเชยทั้งหมด
- แสดงยอดสุทธิที่ต้องจ่าย หรือต้องหักในวันลาออก
- ยกเลิกการลาออกได้

### 🌐 เปลี่ยนภาษา
- สลับ **ไทย ↔ English** ได้ตลอดเวลา (ปุ่ม TH/EN มุมขวาบน)
- จำการตั้งค่าภาษาใน `localStorage`

---

## นโยบายการคำนวณเงินเดือน

| สิ่งที่ทำ | ผลต่อเงินเดือนรายเดือน | ผลต่อการลาออก |
|----------|----------------------|--------------|
| วันลา | **ไม่หักเงิน** | หักในวันลาออก |
| วันชดเชย (ทำอาทิตย์) | **ไม่บวกเงิน** | ได้รับในวันลาออก |
| ยอดสะสม | ยกไปเดือนถัดไปเสมอ ไม่มีวันหมดอายุ | ชำระยอดรวมทั้งหมด |

**สูตรเงินเดือนรายเดือน:** `เงินเดือนเต็ม` (ไม่ว่าจะลากี่วัน)

**สูตรวันลาออก:** `เงินเดือนเดือนสุดท้าย (pro-rate) + (ยอดชดเชยสะสม − ยอดลาสะสม) × อัตรารายวัน`

---

## การ Deploy

ใช้ `deploy.sh` จาก root ของ repo หรือ restart ใน Container Manager ด้วยตนเอง

```bash
# จาก root ของ repo
./deploy.sh
# เลือก restart maid-tracker เมื่อถามทีหลัง
```

## Configuration

ไม่มี `.env` — ไม่มี secrets ที่ต้องตั้งค่า

| Variable | Default | Notes |
|----------|---------|-------|
| `TZ` | `Asia/Bangkok` | ตั้งใน docker-compose.yml |
| `DATA_DIR` | `/data` | ที่เก็บ SQLite DB |

## Data Persistence

Database SQLite อยู่ใน named volume `maid_tracker_data` ที่ `/data/maid_tracker.db`

Volume นี้ไม่ถูกลบเมื่อ restart stack — ข้อมูลปลอดภัย

## DB Schema

```sql
employees (
  id, name, age, nationality, phone, line_id, facebook,
  start_date, monthly_salary, end_date, resign_note, created_at
)

attendance (
  id, employee_id, work_date,
  status CHECK(IN 'work','leave','holiday','compensatory'),
  note
)

salary_payments (
  id, employee_id, year, month,
  period CHECK(IN 1, 2),
  paid_at  -- NULL = ยังไม่จ่าย
)
```

## Routes (Hash-based SPA)

| Hash | View |
|------|------|
| `#/` | รายชื่อแม่บ้าน |
| `#/employee/new` | เพิ่มแม่บ้านใหม่ |
| `#/employee/:id` | ข้อมูลและสรุปภาพรวม |
| `#/employee/:id/edit` | แก้ไขข้อมูล |
| `#/employee/:id/leaves?y=&m=` | ปฏิทิน + รายการวันลา |
| `#/employee/:id/summary?y=&m=` | สรุปรายเดือน |
| `#/employee/:id/payments?y=&m=` | จ่ายเงินเดือน |
| `#/employee/:id/attendance?y=&m=` | ปฏิทินการทำงาน (standalone) |
