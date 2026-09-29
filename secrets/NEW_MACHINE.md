# ย้ายเครื่อง workstation (checklist)

เป้าหมาย: เครื่องใหม่ `git commit` / `git push` / `make secrets` / `./scripts/deploy.sh` ได้เหมือนเครื่องเดิม

ข้อมูลบน NAS ไม่กระทบ — ย้ายแค่ workstation. รายละเอียด vault อื่นๆ ดู [README.md](README.md).

## ต้องพามาเอง (ไม่อยู่ใน git)

| ของ | ที่อยู่ | ใช้ทำอะไร |
| :-- | :-- | :-- |
| age private key | `~/.config/sops/age/keys.txt` | ถอด `vault.sops.yaml` — หายแล้วไม่มีทางกู้ |
| SSH private key | `~/.ssh/id_ed25519` (หรือ `NAS_SSH_KEY`) | deploy.sh ต่อ NAS |
| GitHub credential | `gh auth login` / SSH key / PAT | push ไป `origin` (https) |

`<stack>/.env` และ `.env.deploy` **ไม่ต้องพา** — gitignored, สร้างใหม่ด้วย `make secrets`.

## ขั้นตอน

```bash
# 1. tooling
brew install sops age git gh uv make

# 2. age key — เลือกอย่างใดอย่างหนึ่ง
mkdir -p ~/.config/sops/age
#   ก) วาง key เดิม (Bitwarden / 1Password) ลง keys.txt
chmod 600 ~/.config/sops/age/keys.txt
#   ข) gen ใหม่ แล้วให้เครื่องที่ยังเข้าได้เพิ่ม recipient:
age-keygen -o ~/.config/sops/age/keys.txt      # จด public key age1...
#      เครื่องเก่า: ใส่ public key ใน .sops.yaml
#                   sops updatekeys secrets/vault.sops.yaml
#                   git commit + push
#      เครื่องใหม่: git pull

# 3. SSH ไป NAS
chmod 600 ~/.ssh/id_ed25519
ssh -p <NAS_PORT> <NAS_USER>@<NAS_HOST> echo OK
# ถ้าใช้ NAS_SSH_ALIAS ต้องมี Host block ใน ~/.ssh/config (HostName / Port / IdentityFile)

# 4. Git
gh auth login
git config --global user.name  "<name>"
git config --global user.email "<email>"
git clone https://github.com/FixHarDeZ/centralized-nas-container-management.git
cd centralized-nas-container-management

# 5. Python venv (Makefile ใช้ .venv/bin/python; render_env.py ต้อง PyYAML)
uv sync
# ถ้า uv sync ไม่ลง dep ครบ (uv.lock ไม่ pin อะไร และ sync ลบ package นอก lock):
#   python3 -m venv .venv && .venv/bin/pip install pyyaml pytest ruff

# 6. env ทั้งหมด
make check       # manifest vs vault + test-vault
make secrets     # <stack>/.env ทุก stack + .env.deploy

# 7. ทดสอบ deploy
./scripts/deploy.sh --dry-run
./scripts/deploy.sh -s <stack> -y     # ไม่มี TTY ต้องใส่ -y ไม่งั้น upload ข้ามเงียบๆ
```

## ตรวจว่าใช้ได้

- `make secrets` ผ่าน → age key ถูก. error decrypt = key ไม่ตรง recipient ใน `.sops.yaml`
- `git push` ผ่าน → GitHub auth ถูก
- `deploy.sh --dry-run` ผ่าน → SSH + `.env.deploy` (`NAS_*`) ถูก
- `make test` (optional) → venv ครบ

## ก่อนเครื่องเก่าหาย

- เก็บ age private key ไว้ใน password manager — ไม่มีสำเนาที่อื่น
- ถ้าใช้ `make desk-skills` ต้องพา `~/.claude/skills` มาด้วย (allowlist `ai-deck/skills.list` ดึงจากที่นั่น)
