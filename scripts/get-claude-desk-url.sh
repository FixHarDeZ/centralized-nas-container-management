#!/usr/bin/env bash

# กำหนด Domain และ Port ที่ต้องการ
DOMAIN="fixhardez.synology.me"
PORT="15072"

# ดึงเฉพาะ IPv4 จาก nslookup (ตัดข้อมูล header และเอาบรรทัด Address ล่าสุด)
IP=$(nslookup "$DOMAIN" 2>/dev/null | awk '/^Address: / { print $2 }' | tail -n 1)

if [ -z "$IP" ]; then
    echo "Error: ไม่สามารถ Resolve IP จาก domain: $DOMAIN ได้"
    exit 1
fi

URL="https://${IP}:${PORT}"

# พิมพ์ URL แบบ ANSI OSC 8 Hyperlink (Terminal ส่วนใหญ่ เช่น iTerm2, macOS Terminal, Windows Terminal จะคลิกได้เลย)
printf "URL: \e]8;;%s\e\\%s\e]8;;\e\\\n" "$URL" "$URL"

# ตรวจสอบ OS และสั่งเปิด Default Browser อัตโนมัติ
case "$(uname -s)" in
    Darwin)
        open "$URL"
        ;;
    Linux)
        if command -v xdg-open > /dev/null; then
            xdg-open "$URL" > /dev/null 2>&1 &
        fi
        ;;
    CYGWIN*|MINGW*|MSYS*)
        start "$URL"
        ;;
esac
