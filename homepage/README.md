# Homepage — Fix Home Lab (DS925+)

## โครงสร้าง

```
homepage-nas/
├── .env                   ← credentials ทั้งหมด (อย่า commit!)
├── docker-compose.yml
└── config/
    ├── settings.yaml      ← theme, layout, quicklaunch
    ├── widgets.yaml       ← top bar: datetime, search, weather
    ├── services.yaml      ← service cards ทั้งหมด
    ├── bookmarks.yaml     ← quick bookmarks
    └── docker.yaml        ← docker socket config
```

## วิธีใช้งาน

```bash
docker compose up -d
# เปิด http://192.168.50.200:3000
```

## สิ่งที่เพิ่มเติมจากเดิม

| Feature | รายละเอียด |
|---|---|
| `.env` + `HOMEPAGE_VAR_*` | ย้าย credentials ออกจาก config ทั้งหมด |
| Weather widget | ต้องใส่ OpenWeatherMap API key (ฟรี) |
| NAS Status group | CPU, RAM, Storage, Network แยก card |
| Jellyfin `enableNowPlaying` | เปิดแล้ว + เพิ่ม fields |
| Plex `fields` | แสดง streams, movies, tv |
| Download Station `fields` | แสดง speed + progress |
| Watchtower card | แสดง container status |
| Synology Drive card | เพิ่มใน Note Tools |
| Docker widget | mount socket แบบ read-only |
| Quick Launch | กด `/` แล้ว search ได้เลย |

## Weather API Key (ฟรี)

1. ไปที่ https://openweathermap.org/api
2. สมัคร free account
3. ใส่ key ใน `config/widgets.yaml` บรรทัด `apiKey:`

## หมายเหตุ

- `volume: volume_1` — ปรับให้ตรงกับชื่อ volume จริงใน DSM
- Asus Router ใช้ `ping:` แทน widget เพราะไม่มี native support
- `.env` ควรเพิ่มใน `.gitignore` ถ้าใช้ git
