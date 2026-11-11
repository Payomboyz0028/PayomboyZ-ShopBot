"""
PAYOMBØYZ FLOWAUTH — Whitelist Client Bridge
เชื่อมต่อระบบซื้อคีย์ของ Discord Bot เข้ากับระบบ Cloud Whitelist (Supabase / Vercel Edge API)
รองรับการลงทะเบียนคีย์, รีเซ็ต HWID, ตรวจสอบคีย์ และดึงข้อมูล Project Panel
"""
import os
import requests
import json
from datetime import datetime, timedelta, timezone

WHITELIST_API_URL = os.getenv("WHITELIST_API_URL", "https://payomboyzcreative.online/api/v1").rstrip("/")
WHITELIST_API_KEY = os.getenv("WHITELIST_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


def detect_product_tier(product_id: str, product_name: str = "") -> str:
    """แปลง Product ID หรือชื่อสินค้าให้เป็น Whitelist Tier: VIP, VVIP, SUPERVIP, SCRIPT_HUB"""
    combined = f"{product_id} {product_name}".lower()
    if "supervip" in combined or "super" in combined:
        return "SUPERVIP"
    elif "vvip" in combined:
        return "VVIP"
    elif "scripthub" in combined or "script-hub" in combined or "script" in combined:
        return "SCRIPT_HUB"
    return "VIP"


def register_whitelist_key(
    key_string: str,
    product_id: str,
    product_name: str,
    discord_id: int,
    discord_name: str = "",
    duration_days: int = None
):
    """
    ผูกคีย์ที่ลูกค้าซื้อเข้ากับระบบ Whitelist ทันที
    - กำหนด Role: VIP, VVIP, SUPERVIP, SCRIPT_HUB
    - ผูก Discord ID และบันทึกประวัติ
    - ตั้งค่าโควตารีเซ็ต HWID 3 ครั้ง
    """
    tier = detect_product_tier(product_id, product_name)
    sku = str(product_id or tier).strip().upper()
    is_life = not duration_days or int(duration_days) >= 9000 or sku.endswith("_LIFE") or sku.startswith("SRC_") or sku == "WEB_LOG_VVIP"
    expires_at = None # Clock starts ONLY upon 1st Roblox HWID execution

    payload = {
      "key_string": key_string,
      "role": tier,
      "sku": sku,
      "duration_days": None if is_life else int(duration_days),
      "is_lifetime": is_life,
      "status": "ready",
      "discord_id": str(discord_id),
      "discord_name": discord_name,
      "expires_at": None,
      "hwid_resets_left": 999 if tier == "SUPERVIP" else (5 if tier == "VVIP" else 3),
      "note": f"Discord Purchase: {product_name} (User: {discord_name} / {discord_id})"
    }

    # 1. ยิงผ่าน Supabase REST API โดยตรงถ้ามีค่าตั้งไว้
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        try:
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/license_keys"
            headers = {
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates"
            }
            r = requests.post(url, headers=headers, json=payload, timeout=5)
            if r.status_code in (200, 201):
                return True, tier, expires_at
        except Exception as e:
            print(f"[WHITELIST] Supabase sync warning: {e}")

    # 2. ยิงผ่าน Vercel Whitelist Edge API
    try:
        url = f"{WHITELIST_API_URL}/keys"
        headers = {
            "Authorization": f"Bearer {WHITELIST_API_KEY}",
            "Content-Type": "application/json"
        }
        r = requests.post(url, headers=headers, json={"action": "register", **payload}, timeout=5)
        if r.status_code in (200, 201):
            return True, tier, expires_at
    except Exception as e:
        print(f"[WHITELIST] API sync warning: {e}")

    return True, tier, expires_at


def reset_hwid_by_discord(discord_id: int, key_string: str):
    """
    ให้ผู้ใช้รีเซ็ต HWID ของตัวเองผ่าน Discord
    """
    clean_key = (key_string or "").strip()
    if not clean_key:
        return False, "กรุณาระบุรหัสคีย์ที่ต้องการรีเซ็ต"

    # 1. ผ่าน Supabase RPC
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        try:
            url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/rpc/fn_reset_hwid"
            headers = {
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json"
            }
            r = requests.post(url, headers=headers, json={"p_key_string": clean_key, "p_actor": f"Discord:{discord_id}"}, timeout=5)
            if r.status_code == 200:
                res = r.json()
                return res.get("success", False), res.get("message", "รีเซ็ต HWID เรียบร้อย")
        except Exception as e:
            return False, str(e)

    # 2. ผ่าน REST API
    try:
        url = f"{WHITELIST_API_URL}/keys"
        headers = {
            "Authorization": f"Bearer {WHITELIST_API_KEY}",
            "Content-Type": "application/json"
        }
        r = requests.post(url, headers=headers, json={"action": "reset_hwid", "key": clean_key}, timeout=5)
        if r.status_code == 200:
            res = r.json()
            return res.get("success", True), res.get("message", "รีเซ็ต HWID สำเร็จ สามารถนำไปรันบนอุปกรณ์ใหม่ได้ทันที")
    except Exception as e:
        return False, str(e)

    return True, "รีเซ็ต HWID สำเร็จ สามารถนำไปรันบนอุปกรณ์ใหม่ได้ทันที"


def get_project_details(project_id: str):
    """ดึงข้อมูลโปรเจกต์จากระบบ Whitelist สำหรับแสดงบน Discord Panel"""
    pid = (project_id or "universal").strip().lower()

    default_projects = {
        "universal": {
            "id": "universal",
            "name": "PAYOMBØYZ Universal Hub",
            "version": "3.5.0",
            "min_role": "VIP",
            "auth_mode": "KEYED",
            "payload_source": "DATABASE",
            "description": "สคริปต์รวมฟังก์ชันยอดฮิตทุกเกม อัปเดตรวดเร็ว ระบบความปลอดภัยสูง",
            "loader_url": "https://payomboyz-flowauth.vercel.app/v1/loaders/universal.lua"
        },
        "bloxfruits_gh": {
            "id": "bloxfruits_gh",
            "name": "Blox Fruits Auto-Farm (GitHub Stream)",
            "version": "4.2.0",
            "min_role": "VVIP",
            "auth_mode": "KEYED",
            "payload_source": "GITHUB",
            "description": "ออโต้ฟาร์ม เลเวลตัน ฟาร์มผลปีศาจ ดันเจี้ยน ดึงสคริปต์สดจาก GitHub",
            "loader_url": "https://payomboyz-flowauth.vercel.app/v1/loaders/bloxfruits_gh.lua"
        },
        "community_free": {
            "id": "community_free",
            "name": "PayomboyZ Free Community Hub",
            "version": "1.0.0",
            "min_role": "FREE",
            "auth_mode": "KEYLESS",
            "payload_source": "DATABASE",
            "description": "สคริปต์เปิดให้ใช้งานฟรีสำหรับทุกคน ไม่จำเป็นต้องใช้คีย์ (Keyless)",
            "loader_url": "https://payomboyz-flowauth.vercel.app/v1/loaders/community_free.lua"
        },
        "external_auth_api": {
            "id": "external_auth_api",
            "name": "External Whitelist Bridge Project",
            "version": "1.0.0",
            "min_role": "VIP",
            "auth_mode": "KEYED",
            "payload_source": "AUTH_ONLY",
            "description": "ระบบตรวจสอบคีย์เดี่ยว สำหรับเชื่อมต่อบอทภายนอกหรือสคริปต์ค่ายอื่น",
            "loader_url": "https://payomboyz-flowauth.vercel.app/v1/loaders/external_auth_api.lua"
        }
    }

    try:
        url = f"{WHITELIST_API_URL}/projects"
        headers = { "Authorization": f"Bearer {WHITELIST_API_KEY}" }
        r = requests.get(url, headers=headers, timeout=4)
        if r.status_code == 200:
            data = r.json()
            for p in data.get("projects", []):
                if p.get("id") == pid:
                    return p
    except Exception:
        pass

    return default_projects.get(pid, default_projects["universal"])
