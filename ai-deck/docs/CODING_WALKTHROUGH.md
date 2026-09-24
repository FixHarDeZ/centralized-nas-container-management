# ใช้ AI Deck พัฒนา GitHub repository

ตัวอย่างนี้ใช้ `https://github.com/FixHarDeZ/centralized-nas-container-management` โดยเก็บ source code ใน coding workspace ถาวรบน NAS ไม่ต้องอัปโหลดลง `in/` แต่ละ task มี branch `desk/<workspace-id>` ของตัวเอง

## 1. เตรียมบัญชีครั้งแรก

เปิด AI Deck → **Projects & deploy → Project → Open Terminal** แล้วรัน:

```sh
gh auth login --web --git-protocol https
gh auth setup-git
git config --global user.name "Your Name"
git config --global user.email "YOUR_GITHUB_NOREPLY_EMAIL"
gh auth status
```

ทำ device login ตาม URL/code ที่ terminal แสดง และเลือกบัญชีที่มีสิทธิ์ push repo นี้ การ clone public repo ไม่ต้อง login แต่ push และ private repo ต้องมีสิทธิ์ GitHub ก่อน ข้อมูล login อยู่ใน coding home แยกจากโหมดเอกสาร รุ่นนี้ใช้ coding worker/home ร่วมกันภายในทีมที่ไว้ใจกัน ไม่เหมาะกับผู้ใช้ที่ไม่ไว้ใจกัน

Claude ใช้บัญชีที่ login ไว้ใน worker home (`claude auth login` ใน **coding Terminal**; ไม่ใช้ setup-token จาก environment) เพื่อให้แชทและโควตาใช้บัญชีเดียวกัน ส่วน Codex ต้องลงชื่อเข้าใช้ใน **coding Terminal** อีกครั้ง (`codex login --device-auth`) เพราะ coding home แยกจาก document home

## 2. เปิดงานใหม่จาก GitHub

ใน **Projects** กรอก:

- **GitHub repository URL:** `https://github.com/FixHarDeZ/centralized-nas-container-management`
- **Base branch:** `main`
- กด **Clone & start task**

ระบบ fetch repo และสร้าง task branch ให้ ไม่แก้ `main` โดยตรง เลือก task เดิมจากรายการด้านบนเพื่อทำต่อได้หลัง reload หรือ container restart การสร้าง task ใหม่จะใช้ commit ล่าสุดของ base branch

## 3. ให้ AI อ่าน repo และแก้โค้ด

เลือก Claude หรือ Codex แล้วส่งตัวอย่างนี้:

> อ่าน AGENTS.md, CLAUDE.md และ ai-deck/.notes/00_INDEX.md ก่อน แล้วเพิ่มปุ่มคัดลอก commit SHA ในหน้าจอ Projects ของ ai-deck ตรวจการทำงานบนจอมือถือด้วย รัน tests ที่เกี่ยวข้อง สรุป diff ให้ดู ยังไม่ commit หรือ deploy

Chat และ Terminal ของ task นี้ใช้ working directory เดียวกัน ประวัติ chat แยกตาม workspace สามารถสลับไป Terminal เพื่อตรวจคำสั่งหรือรันเองได้

คำสั่งเริ่มต้นสำหรับ repo นี้:

```sh
pwd
git status --short --branch
python3 -m venv .venv
.venv/bin/pip install pytest PyYAML
.venv/bin/python -m pytest ai-deck/tests -q
```

ติดตั้ง dependencies เพิ่มตาม stack ที่แก้ หาก test UI ต้องใช้ Chrome ให้ติดตั้ง browser runtime ตาม test harness หรือรันส่วนนั้นบนเครื่องพัฒนา การทดสอบที่ต้องใช้ SOPS/production credentials ให้ทำผ่านเครื่อง trusted runner; coding worker ไม่มี age key หรือ SSH deploy key

## 4. ตรวจ diff และทดสอบ

เปิด **Projects & deploy → Project → Refresh status** เพื่อดู branch, SHA, รายการไฟล์และ tracked diff ไฟล์ใหม่ที่ยังไม่ tracked จะแสดงใน status แต่ยังไม่มีเนื้อหาใน tracked diff ให้ AI หรือ terminal อ่านไฟล์นั้นเพิ่มเติม

**Test changes** และ **Commit & push…** เติมข้อความลงช่อง chat ให้ตรวจและกดส่งเอง ปุ่มเหล่านี้ไม่ได้ commit/push ทันที

## 5. Commit และ push task branch

หลังตรวจ diff และ tests แล้ว สั่ง:

> commit เฉพาะไฟล์ของงานนี้ด้วยข้อความที่สื่อความหมาย แล้ว push task branch ปัจจุบันไป origin สรุป commit SHA และผล tests

หรือรันเอง โดยระบุไฟล์ให้ตรงงาน:

```sh
git add ai-deck/ui/index.html ai-deck/ui/workspaces.js
git commit -m "feat(ai-deck): copy project commit SHA"
git push -u origin HEAD
gh pr create --base main --title "Copy project commit SHA" --body "Adds a copy action for the selected project revision."
```

ตัวอย่างชื่อไฟล์เป็นแนวทาง ให้ stage tests/เอกสารที่เกี่ยวข้องด้วย ตรวจ PR และ merge เข้า `main` ตาม workflow ของทีม จะสั่ง AI ทำขั้นตอนเหล่านี้ก็ได้

## 6. Deploy commit ที่ merge แล้ว

profile `nas-ai-deck` ยอมรับเฉพาะ **full SHA ของ tip บน GitHub branch main** เท่านั้น จึงใช้ SHA ของ task branch ก่อน merge ไม่ได้ (โดยเฉพาะ squash merge จะได้ SHA ใหม่)

```sh
git fetch origin main
git rev-parse refs/remotes/origin/main
```

คัดลอก SHA 40 ตัว → **Projects & deploy → Deploy**:

1. เลือก **nas-ai-deck**
2. วาง SHA ของ `origin/main` ใน **Full commit SHA** แทนค่า task SHA ที่เติมให้อัตโนมัติ
3. กด **Deploy commit**
4. ดูสถานะ `queued → running → succeeded` หรือ `failed` พร้อม log

Mac จะ clone checkout ใหม่ ตรวจ SHA/branch อีกครั้ง ถอด SOPS บน Mac เรียก deployment script เดิม แล้วตรวจ `/health` ว่า NAS กำลังรัน revision ตรงกับ SHA ที่ขอจริง จึงรายงาน succeeded ข้อมูล document home, coding home และ workspaces อยู่ใน persistent volumes

profile นี้ deploy เฉพาะ stack **ai-deck** การแก้ `shorts-factory` หรือ stack อื่นต้องเพิ่ม profile ที่อนุญาต stack นั้นบน trusted Mac ก่อน ไม่สามารถส่ง arbitrary deploy command จาก UI ได้

## 7. ทำงานต่อและข้อจำกัดรุ่นแรก

- เปิด task เดิมเพื่อแก้ต่อ หรือสร้าง task ใหม่จาก `main` สำหรับงานใหม่
- Mac ต้องเปิดเครื่อง ตื่นอยู่ มีเครือข่าย และ user login เพื่อให้ LaunchAgents ทำงาน ถ้า Mac offline งาน deploy จะไม่สำเร็จ
- การ commit/push ทำผ่าน AI/terminal และ GitHub credentials ส่วน deploy ทำผ่าน profile บน Mac แยกกัน
- Test/runtime ที่ต้องใช้ Docker daemon ยังรันใน coding worker ไม่ได้ เพราะไม่มี Docker socket
- หาก deploy failed ให้ดู log และตรวจสภาพ NAS ก่อน retry โดยเฉพาะกรณี Mac หลับหรือถูกปิดระหว่าง deploy

รายละเอียดติดตั้งและแก้ปัญหา runner/tunnel: [CODING_DEPLOY.md](CODING_DEPLOY.md)
