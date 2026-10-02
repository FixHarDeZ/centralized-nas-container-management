# ทำงานหลาย repo ใน Chat เดียว (Task กลุ่ม) — คู่มือฉบับทำตาม

ใช้เมื่อต้องแก้หลาย repo ไปพร้อมกัน เช่น `jenkins-pipeline` + `jenkins-library`
AI จะเห็นทุก repo ในแชทเดียว แต่ละ repo ยัง commit / ดึงกลับ / merge แยกกันเหมือนเดิม

> ยังไม่เคยใช้ `desk-sync` เลย → ทำ "ตั้งค่าครั้งแรก" ใน [LOCAL_BUNDLE_SETUP.md](LOCAL_BUNDLE_SETUP.md) ก่อน (ทำครั้งเดียว)

---

## ขั้นที่ 1 — ส่ง repo ขึ้นเป็นกลุ่ม (บน Mac)

```bash
desk-sync group up jenkins ~/work/jenkins-pipeline ~/work/jenkins-library --email <อีเมลงาน>
```

- `jenkins` = ชื่อกลุ่ม (ตัวเล็ก/ตัวเลข/`.` `_` `-`) ตั้งอะไรก็ได้
- ตามด้วย path ของทุก repo (2–8 repo) จะรันจากโฟลเดอร์ไหนก็ได้
- เสร็จแล้วจะขึ้น `group 'jenkins' created`

## ขั้นที่ 2 — สั่งงาน AI (บนหน้า desk)

1. เปิดหน้า desk → ช่องเลือกโปรเจกต์ → เลือก **`jenkins (group: jenkins-pipeline, jenkins-library)`**
2. คุยใน **Chat** ตามปกติ ตัวอย่างประโยคเปิด:

   > แก้ step `deployApp` ใน jenkins-library ให้รับ parameter `region` แล้วอัปเดต Jenkinsfile ใน jenkins-pipeline ให้ส่งค่านี้
   > เสร็จแล้ว **commit แยกในแต่ละ repo**

3. ⚠️ ต้องให้ AI **commit** ก่อนเสมอ — ส่งกลับ Mac ได้เฉพาะงานที่ commit แล้ว

เช็คความคืบหน้า: **Projects → Refresh** จะเห็นแต่ละ repo มีกี่ commit / ไฟล์ค้างอะไร

## ขั้นที่ 3 — ดึงงานกลับ (บน Mac)

```bash
desk-sync group down jenkins
```

- ดึงทุก repo ในคำสั่งเดียว repo ที่ AI ไม่ได้แตะจะขึ้น `nothing to bring back` (ปกติ ไม่ใช่ error)
- แต่ละ repo จะได้ branch `desk/<id>` พร้อมรายการ commit ที่พิมพ์ให้ดู

## ขั้นที่ 4 — ตรวจแล้ว merge / push (บน Mac ทีละ repo)

```bash
cd ~/work/jenkins-library
git log --oneline HEAD..desk/<id>    # ดูว่ามีอะไรมา (id ดูจากขั้นที่ 3)
git merge desk/<id>
git push

cd ~/work/jenkins-pipeline
# ทำเหมือนกัน
```

---

## ทำต่อรอบถัดไป

Mac มี commit ใหม่ (เช่นเพื่อนร่วมทีม push มา) อยากส่งตามขึ้นไป:

```bash
desk-sync group up jenkins           # ไม่ต้องใส่ path แล้ว จำไว้ให้
```

แล้วบอก AI ใน Chat ว่า "rebase แต่ละ repo ไปบน origin/main"

ดูสถานะ: `desk-sync group status jenkins`

## เลิกใช้กลุ่ม

หน้า desk → เลือกกลุ่ม → **Projects → Ungroup (keeps tasks)** กด 2 ครั้ง

- repo กลับไปเป็น task เดี่ยว งานใน repo **ไม่หาย**
- ถ้า AI ทิ้งไฟล์ไว้ที่โฟลเดอร์กลุ่ม (นอก repo) จะเตือนชื่อไฟล์ก่อน กดอีกครั้ง = ลบไฟล์พวกนั้น
- จะลบงานจริงต้องเข้าไปลบ task ของแต่ละ repo เอง

## ทำผ่านหน้าเว็บแทน `desk-sync group up`

1. ส่งทีละ repo ก่อน: `cd <repo> && desk-sync up --email <อีเมลงาน>` (หรือปุ่ม Local bundle)
2. หน้า desk → **Projects → Local bundle** → ส่วน **Group local tasks**
3. ติ๊ก task ที่ต้องการ ใส่ชื่อกลุ่ม → **Group tasks**

## ปัญหาที่เจอบ่อย

| อาการ | แก้ |
|---|---|
| `Task is already in a group` | repo นั้นอยู่กลุ่มอื่นแล้ว → Ungroup กลุ่มเดิมก่อน |
| `Grouped tasks must come from different projects` | ใส่ repo เดียวกันซ้ำ |
| `This task moved … wait for the current turn` | รวม/แยกกลุ่มระหว่าง AI กำลังตอบ → รอจบแล้วส่งใหม่ |
| แชทเก่าของ repo หายไปจากกลุ่ม | ปกติ: แชทผูกกับโฟลเดอร์ แชทของ task เดี่ยวไม่ตามมา |
| `no group 'jenkins'` | ยังไม่เคย `group up` บน Mac เครื่องนี้ |
| อื่นๆ (`401`, `Keychain`, `--full`) | ดูตารางใน [LOCAL_BUNDLE_SETUP.md](LOCAL_BUNDLE_SETUP.md) |

> ⚠️ โค้ดบริษัท: เงื่อนไขเดียวกับ Local bundle — โค้ดไปอยู่บน NAS ส่วนตัวและส่งให้ AI ผ่านบัญชีส่วนตัว เช็คนโยบายก่อน
