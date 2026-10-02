# ใช้ ai-desk เขียนโค้ดจาก repo ในเครื่อง (Local bundle)

สำหรับ repo ที่ Mac clone ได้ (เช่นอยู่หลัง VPN บริษัท) แต่ ai-desk บน NAS ต่อไปหาไม่ได้
หลักการ: Mac แพ็ก repo เป็นไฟล์ `.bundle` (มี history ครบ) → ส่งขึ้น desk → ให้ AI แก้และ commit → ดึง commit กลับลง Mac → ตรวจแล้ว merge/push เองจาก Mac

```
Mac ──desk-sync up──▶ ai-desk (task desk/<id>) ──AI แก้ + commit──▶ desk-sync down ──▶ Mac merge + push
```

> ⚠️ ก่อนใช้กับโค้ดบริษัท: เช็คนโยบายบริษัทก่อน โค้ดจะไปอยู่บน NAS ส่วนตัว และถูกส่งให้ Claude/Codex ผ่านบัญชีส่วนตัว
> คนในบ้านที่มีบัญชี coding บน desk อ่านโค้ดนี้ได้ และ IT บริษัทอาจเห็นการอัปโหลดผ่านโปรแกรมตรวจเครื่อง/VPN

---

## ตั้งค่าครั้งแรก (ทำครั้งเดียว)

**1. เอาสคริปต์มาไว้ใน PATH**

```bash
mkdir -p ~/bin
cp <repo นี้>/scripts/desk-sync ~/bin/
chmod +x ~/bin/desk-sync
# ถ้า ~/bin ยังไม่อยู่ใน PATH:
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

**2. สร้างไฟล์ตั้งค่า**

```bash
mkdir -p ~/.config/desk-sync
cat > ~/.config/desk-sync/config <<'EOF'
DESK_URL=https://<โดเมน NAS>:15072
DESK_USER=<ชื่อผู้ใช้ที่ใช้ login หน้า desk>
EOF
```

**3. เก็บรหัสผ่านไว้ใน Keychain** (ไม่เขียนลงไฟล์)

```bash
security add-generic-password -s desk-sync -a <ชื่อผู้ใช้> -w
# ระบบจะถามรหัสผ่าน พิมพ์รหัสเดียวกับที่ใช้เข้าหน้า desk
```

เปลี่ยนรหัสภายหลัง: ลบของเดิมด้วย `security delete-generic-password -s desk-sync -a <ชื่อผู้ใช้>` แล้วเพิ่มใหม่

---

## ใช้งานประจำ

**ส่งโค้ดขึ้นครั้งแรก** — `cd` เข้า repo บนเครื่องก่อน

```bash
desk-sync up --email <อีเมลงาน>
```

- จะได้ task ใหม่บน desk ชื่อ branch `desk/<id>` เริ่มจาก branch ที่ checkout อยู่
- `--email` (และ `--name`) = ชื่อผู้ commit ของงานนี้ ไม่ใส่ก็ได้
- ถ้ามีไฟล์ที่หน้าตาเหมือนรหัสลับ (`.env`, `*.pem` ฯลฯ) จะขึ้นเตือน
- ตั้งชื่อโปรเจกต์เองได้ด้วย `--slug my-app` (ไม่ใส่ = ใช้ชื่อโฟลเดอร์)

**สั่งงาน AI** — เปิดหน้า desk → เลือกโปรเจกต์ `<ชื่อ> (local)` → คุยใน Chat
อย่าลืมบอกให้ **commit** งาน (ส่งกลับได้เฉพาะสิ่งที่ commit แล้ว)

**ดึงงานกลับลง Mac**

```bash
desk-sync down
git log --oneline HEAD..desk/<id>     # ดูว่ามีอะไรมาบ้าง (สคริปต์พิมพ์ให้แล้ว)
git merge desk/<id>                   # หรือ rebase / cherry-pick ตามสะดวก
git push                              # push จาก Mac ตามปกติ
```

- ถ้าบน desk ยังมีไฟล์ไม่ได้ commit จะถูกปฏิเสธ → ใช้ `desk-sync down --force` เพื่อเอาเฉพาะที่ commit แล้ว
- สคริปต์ไม่ merge ให้เอง และไม่ทับ commit ที่คุณทำบน branch `desk/<id>` ในเครื่อง

**ฝั่ง Mac มี commit ใหม่ อยากส่งตามขึ้นไป**

```bash
desk-sync up          # ส่งเฉพาะ commit ใหม่ ไฟล์เล็ก
```

แล้วบอก AI ใน Chat ว่า "rebase ไปบน origin/main" (หรือ branch ที่ใช้)

**ดูสถานะ**

```bash
desk-sync status      # โปรเจกต์ไหน task ไหน มี commit ที่ยังไม่ส่งกี่อัน
```

---

## ทำหลาย repo พร้อมกัน (Task กลุ่ม)

คู่มือทีละขั้น: [TASK_GROUP_GUIDE.md](TASK_GROUP_GUIDE.md)

เช่น repo หนึ่งเก็บ Jenkins pipeline อีก repo เก็บ Jenkins shared library แล้วต้องแก้ไปด้วยกัน

```bash
desk-sync group up jenkins ~/work/jenkins-pipeline ~/work/jenkins-library --email <อีเมลงาน>
```

- แต่ละ repo ยังได้ task กับ branch `desk/<id>` ของตัวเองเหมือนเดิม (repo ที่เคย `up` แล้วใช้ task เดิม)
- desk ย้ายทั้งสอง repo มาอยู่เป็นโฟลเดอร์พี่น้องกันในโฟลเดอร์เดียว:
  `jenkins/jenkins-pipeline/` กับ `jenkins/jenkins-library/` พร้อมไฟล์ `CLAUDE.md`/`AGENTS.md` บอก AI ว่ามีกี่ repo และต้อง commit แยกกัน
- หน้า desk → เลือก `jenkins (group: …)` → คุยใน Chat ทีเดียว AI เห็นและแก้ได้ทุก repo
- บอก AI ให้ **commit ในแต่ละ repo** (โฟลเดอร์กลุ่มเองไม่ใช่ git repo)

ดึงงานกลับทุก repo ในคำสั่งเดียว / ส่ง commit ใหม่ขึ้นไปทุก repo:

```bash
desk-sync group down jenkins       # รัน down ในทุก repo
desk-sync group up jenkins         # ครั้งต่อไปไม่ต้องใส่ path แล้ว จำไว้ที่ ~/.config/desk-sync/groups/jenkins
desk-sync group status jenkins
```

จากนั้น merge/push ทีละ repo บน Mac เหมือนเดิม

ทำผ่านหน้าเว็บก็ได้: **Projects → Local bundle → Group local tasks** ติ๊ก task ตั้งแต่ 2 อันขึ้นไป (ต่างโปรเจกต์กัน สูงสุด 8) แล้วกด **Group tasks**

- ปุ่ม **Ungroup** ในกลุ่ม = ย้าย repo กลับเป็น task เดี่ยว **ไม่ลบงาน** (commit/ไฟล์ที่ยังไม่ commit อยู่ครบ)
  ถ้า AI ทิ้งไฟล์ไว้ที่โฟลเดอร์กลุ่มเอง (นอก repo) จะถูกถามก่อน กดซ้ำ = ลบไฟล์พวกนั้นทิ้ง
- `group down` repo ที่ AI ไม่ได้ commit อะไรจะขึ้นว่า `nothing to bring back` แล้วข้ามไป ไม่นับเป็น error
- ลบ task ของ repo ไหนทิ้ง กลุ่มจะเหลือ repo ที่เหลือ
- Chat history ที่คุยใน task เดี่ยวก่อนรวมกลุ่ม จะไม่ตามมาในแชทของกลุ่ม (แชทผูกกับโฟลเดอร์)

---

## ไม่อยากใช้สคริปต์ (ทำผ่านหน้าเว็บ)

1. บน Mac: `git bundle create app.bundle --branches HEAD`
2. หน้า desk → **Projects** → **Local bundle** → เลือกไฟล์, ตั้งชื่อโปรเจกต์ → **Upload & start task**
3. ทำงานใน Chat ให้ AI commit
4. **Projects → Current task → Download changes** ได้ไฟล์ `desk-<ชื่อ>-xxxx.bundle`
5. บน Mac: `git fetch ~/Downloads/desk-<ชื่อ>-xxxx.bundle desk/<id>:desk/<id>` แล้ว merge

ส่ง commit ใหม่จาก Mac ผ่านเว็บ: `git bundle create upd.bundle <commit ที่ส่งล่าสุด>..main` → ปุ่ม **Upload update**

---

## ปัญหาที่เจอบ่อย

| อาการ | แก้ |
|---|---|
| `desk is missing earlier commits` | `desk-sync up --full` |
| `task ... is gone on the desk` (task ถูกลบ) | `desk-sync up --new` เริ่ม task ใหม่ |
| `no Keychain item` | ทำขั้นตอน 3 ของการตั้งค่า |
| `401` | user/รหัสผ่านใน config หรือ Keychain ไม่ถูก |
| `Nothing to export` | AI ยังไม่ได้ commit — สั่งให้ commit ก่อน |
| `local desk/<id> has commits the desk does not` | branch ในเครื่องมี commit ของคุณเอง: `git branch -m desk/<id> desk/<id>-local` แล้ว `down` ใหม่ |
| อัปโหลดใหญ่เกิน | จำกัด 300 MB ต่อครั้ง |
| `Task is already in a group` | task นั้นอยู่กลุ่มอื่นแล้ว: Ungroup กลุ่มเดิมก่อน |
| `Grouped tasks must come from different projects` | ติ๊ก task ของโปรเจกต์เดียวกันสองอัน |

## รู้ไว้

- ปุ่ม Push / Deploy ถูกซ่อนสำหรับโปรเจกต์ local — push ทำจาก Mac เท่านั้น
- ลบ task บน desk แล้ว ตัว repo cache ยังอยู่บน NAS (เหมือนโปรเจกต์ GitHub) ส่งขึ้นชื่อเดิมครั้งหน้าจะเร็วขึ้น
- สถานะของสคริปต์เก็บที่ `.git/desk-sync` ใน repo ของคุณ (ไม่ติดไปกับ git)
