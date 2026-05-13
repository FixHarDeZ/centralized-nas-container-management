import os
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

# --- Load .env ---
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
# Parent Page ID (Claude-work-notes)
PARENT_PAGE_ID = "10b5710fcc06413ab46ad9512e8003ad"

def get_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

def create_or_get_page(parent_id, title, is_database=False):
    """ค้นหา Page หรือสร้างใหม่ถ้ายังไม่มี"""
    search_url = "https://api.notion.com/v1/search"
    query = {
        "query": title,
        "filter": {"property": "object", "value": "page"}
    }
    response = requests.post(search_url, headers=get_headers(), json=query)
    results = response.json().get("results", [])
    
    # ถ้าเจอ page ที่ชื่อตรงกัน ให้ส่ง ID กลับ
    for result in results:
        properties = result.get("properties", {})
        # Notion มีวิธีเก็บ title ต่างกันในแต่ละแบบ (Page vs Database)
        title_list = properties.get("title", {}).get("title", []) or \
                     properties.get("title", []) or \
                     properties.get("Name", {}).get("title", [])
        
        if title_list and title_list[0].get("plain_text") == title:
            return result["id"]

    # ถ้าไม่เจอ ให้สร้างใหม่
    create_url = "https://api.notion.com/v1/pages"
    new_page_data = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": [{"text": {"content": title}}]
        }
    }
    create_res = requests.post(create_url, headers=get_headers(), json=new_page_data)
    return create_res.json().get("id")

def _chunk_text(text, size=1900):
    """Split text into chunks no larger than `size` characters."""
    return [text[i:i+size] for i in range(0, len(text), size)]

def append_toggle_entry(parent_id, title, content):
    """สร้าง Toggle list ใน Notion พร้อม paragraph หลาย block ถ้า content ยาวเกิน 2000 ตัวอักษร"""
    url = f"https://api.notion.com/v1/blocks/{parent_id}/children"
    now = datetime.now().strftime("%H:%M")

    chunks = _chunk_text(content)
    paragraph_blocks = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}]
            }
        }
        for chunk in chunks
    ]

    data = {
        "children": [
            {
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": [{"type": "text", "text": {"content": f"{now} — {title}"}}],
                    "children": paragraph_blocks
                }
            }
        ]
    }
    res = requests.patch(url, headers=get_headers(), json=data)
    return res.status_code == 200

def sync_to_notion(title, content):
    if not NOTION_TOKEN:
        print("❌ Error: NOTION_TOKEN not found.")
        return

    try:
        # 1. จัดการ Year Page (2026)
        year_str = datetime.now().strftime("%Y")
        year_page_id = create_or_get_page(PARENT_PAGE_ID, year_str)
        
        # 2. จัดการ Date Page (2026-05-12)
        date_str = datetime.now().strftime("%Y-%m-%d")
        date_page_id = create_or_get_page(year_page_id, date_str)
        
        # 3. เพิ่ม Toggle Entry
        success = append_toggle_entry(date_page_id, title, content)
        
        if success:
            print(f"✅ Successfully synced to Notion: {title}")
        else:
            print("⚠️ Failed to append entry.")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        sync_to_notion(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python3 scripts/sync_notion.py 'Title' 'Content'")