# -*- coding: utf-8 -*-
"""
Roblox Player Lookup Service & Views for PAYOMBØYZ
Provides high-speed lookup via Roblox public APIs with 5-minute caching.
"""
import time
import asyncio
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional, Tuple, Dict
import aiohttp
import discord

PANEL_CHANNEL_ID = 1564687462335389709
RESULT_CHANNEL_ID = 1564687817374699631
BRAND_COLOR = 0xEE2737
BRAND_PANEL_TITLE = "PAYOMBØYZ • ROBLOX LOOKUP"
CACHE_TTL_SECONDS = 300
REQUEST_TIMEOUT = 10

THAI_MONTHS = [
    '', 'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
    'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'
]

@dataclass
class RobloxUser:
    user_id: int
    username: str
    display_name: str
    is_banned: bool
    created_at_thai: str
    account_age_thai: str
    description: str
    online_status: str
    last_location: str
    friends_count: int
    followers_count: int
    followings_count: int
    groups_count: int
    avatar_bust_url: str
    profile_url: str


class RobloxService:
    _session: Optional[aiohttp.ClientSession] = None
    _cache: Dict[str, Tuple[float, RobloxUser]] = {}

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            cls._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PayomboyZ-RobloxLookup/1.0",
                    "Accept": "application/json"
                }
            )
        return cls._session

    @classmethod
    async def close_session(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()

    @staticmethod
    def format_thai_date(iso_str: str) -> str:
        try:
            clean_iso = iso_str.replace('Z', '+00:00')
            dt = datetime.fromisoformat(clean_iso)
            be_year = dt.year + 543
            month_str = THAI_MONTHS[dt.month] if 1 <= dt.month <= 12 else str(dt.month)
            time_str = dt.strftime("%H:%M")
            return f"{dt.day} {month_str} {be_year} {time_str}"
        except Exception:
            return iso_str[:10]

    @staticmethod
    def calculate_account_age(iso_str: str) -> str:
        try:
            clean_iso = iso_str.replace('Z', '+00:00')
            created_dt = datetime.fromisoformat(clean_iso)
            now_dt = datetime.now(timezone.utc)
            delta = now_dt - created_dt
            total_days = max(0, delta.days)
            years = total_days // 365
            rem_days = total_days % 365
            months = rem_days // 30
            days = rem_days % 30
            parts = []
            if years > 0: parts.append(f"{years} ปี")
            if months > 0: parts.append(f"{months} เดือน")
            if days > 0 or len(parts) == 0: parts.append(f"{days} วัน")
            return " ".join(parts)
        except Exception:
            return "ไม่สามารถคำนวณได้"

    @classmethod
    async def resolve_user_id(cls, query: str) -> Optional[int]:
        query = query.strip()
        if query.isdigit():
            return int(query)

        session = await cls.get_session()
        url = "https://users.roblox.com/v1/usernames/users"
        payload = {"usernames": [query], "excludeBannedUsers": False}
        try:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    user_list = data.get("data", [])
                    if user_list:
                        return user_list[0].get("id")
        except Exception:
            pass
        return None

    @classmethod
    async def lookup_player(cls, query: str) -> Tuple[bool, Optional[RobloxUser], str]:
        clean_query = query.strip().lower()
        now = time.time()
        if clean_query in cls._cache:
            cache_time, cached_user = cls._cache[clean_query]
            if now - cache_time < CACHE_TTL_SECONDS:
                return True, cached_user, "ดึงจากแคชสำเร็จ"

        user_id = await cls.resolve_user_id(query)
        if not user_id:
            return False, None, f"ไม่พบข้อมูลผู้เล่นสำหรับคำค้นหา: `{query}`"

        session = await cls.get_session()

        async def fetch_user_details():
            url = f"https://users.roblox.com/v1/users/{user_id}"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200: return await resp.json()
            except Exception: pass
            return None

        async def fetch_presence():
            url = "https://presence.roblox.com/v1/presence/users"
            try:
                async with session.post(url, json={"userIds": [user_id]}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pres_list = data.get("userPresences", [])
                        if pres_list: return pres_list[0]
            except Exception: pass
            return None

        async def fetch_friends_count():
            url = f"https://friends.roblox.com/v1/users/{user_id}/friends/count"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("count", 0)
            except Exception: pass
            return 0

        async def fetch_followers_count():
            url = f"https://friends.roblox.com/v1/users/{user_id}/followers/count"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("count", 0)
            except Exception: pass
            return 0

        async def fetch_followings_count():
            url = f"https://friends.roblox.com/v1/users/{user_id}/followings/count"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("count", 0)
            except Exception: pass
            return 0

        async def fetch_groups_count():
            url = f"https://groups.roblox.com/v1/users/{user_id}/groups/roles"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return len(data.get("data", []))
            except Exception: pass
            return 0

        async def fetch_avatar_bust():
            url = f"https://thumbnails.roblox.com/v1/users/avatar-bust?userIds={user_id}&size=420x420&format=Png&isCircular=false"
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        thumb_list = data.get("data", [])
                        if thumb_list: return thumb_list[0].get("imageUrl", "")
            except Exception: pass
            return ""

        results = await asyncio.gather(
            fetch_user_details(),
            fetch_presence(),
            fetch_friends_count(),
            fetch_followers_count(),
            fetch_followings_count(),
            fetch_groups_count(),
            fetch_avatar_bust(),
            return_exceptions=True
        )

        user_details = results[0] if isinstance(results[0], dict) else None
        if not user_details:
            return False, None, f"ไม่สามารถดึงข้อมูลพื้นฐานของ User ID: `{user_id}` ได้"

        presence = results[1] if isinstance(results[1], dict) else {}
        friends_cnt = results[2] if isinstance(results[2], int) else 0
        followers_cnt = results[3] if isinstance(results[3], int) else 0
        followings_cnt = results[4] if isinstance(results[4], int) else 0
        groups_cnt = results[5] if isinstance(results[5], int) else 0
        avatar_bust = results[6] if isinstance(results[6], str) else ""

        # Map presence
        presence_type = presence.get("userPresenceType", 0)
        last_loc = presence.get("lastLocation", "")
        if presence_type == 1:
            online_str = "🟢 ออนไลน์บนเว็บไซต์ (Website)"
            location_str = "🌐 เว็บไซต์ Roblox"
        elif presence_type == 2:
            online_str = "🎮 กำลังเล่นเกม (In-Game)"
            location_str = f"🕹️ {last_loc}" if last_loc else "🎮 ในเซิร์ฟเวอร์เกม"
        elif presence_type == 3:
            online_str = "🛠️ กำลังสร้างแมพ (Studio)"
            location_str = f"🔨 {last_loc}" if last_loc else "🛠️ Roblox Studio"
        else:
            online_str = "⚪ ออฟไลน์ (Offline)"
            location_str = "🚪 ไม่ได้อยู่ในเกม"

        created_iso = user_details.get("created", "")
        created_thai = cls.format_thai_date(created_iso)
        age_thai = cls.calculate_account_age(created_iso)
        desc = user_details.get("description", "").strip()
        if not desc: desc = "ไม่ได้ระบุชีวประวัติ"
        elif len(desc) > 300: desc = desc[:297] + "..."

        roblox_user = RobloxUser(
            user_id=user_id,
            username=user_details.get("name", "Unknown"),
            display_name=user_details.get("displayName", "Unknown"),
            is_banned=user_details.get("isBanned", False),
            created_at_thai=created_thai,
            account_age_thai=age_thai,
            description=desc,
            online_status=online_str,
            last_location=location_str,
            friends_count=friends_cnt,
            followers_count=followers_cnt,
            followings_count=followings_cnt,
            groups_count=groups_cnt,
            avatar_bust_url=avatar_bust,
            profile_url=f"https://www.roblox.com/users/{user_id}/profile"
        )

        cls._cache[clean_query] = (now, roblox_user)
        cls._cache[str(user_id)] = (now, roblox_user)
        cls._cache[roblox_user.username.lower()] = (now, roblox_user)

        return True, roblox_user, "ดึงข้อมูลสำเร็จ"


def build_player_embed(user: RobloxUser) -> discord.Embed:
    status_text = "🔨 ถูกแบน" if user.is_banned else "✅ ปกติ"
    description = (
        f"**🎮 ข้อมูลผู้เล่น**\n"
        f"`{user.username}`\n\n"
        f"**▶ ข้อมูลทั่วไป**\n"
        f"`🆔 รหัสผู้ใช้` {user.user_id}\n"
        f"`🏷️ ชื่อผู้ใช้` {user.username}\n"
        f"`📛 ชื่อที่แสดง` {user.display_name}\n"
        f"`⚡ สถานะบัญชี` {status_text}\n"
        f"`🌐 สถานะออนไลน์` {user.online_status}\n"
        f"`📍 ตำแหน่งล่าสุด` {user.last_location}\n"
        f"`📅 สร้างเมื่อ` {user.created_at_thai}\n"
        f"`⌛ อายุบัญชี` {user.account_age_thai}\n"
        f"`✍️ ชีวประวัติ` {user.description}\n\n"
        f"**▶ สังคม**\n"
        f"`👥 เพื่อน` {user.friends_count} คน\n"
        f"`❤️ ผู้ติดตาม` {user.followers_count:,} คน\n"
        f"`➕ กำลังติดตาม` {user.followings_count:,} คน\n"
        f"`🏘️ กลุ่มที่เข้าร่วม` {user.groups_count} กลุ่ม"
    )

    embed = discord.Embed(
        description=description,
        color=discord.Color(BRAND_COLOR)
    )
    if user.avatar_bust_url:
        embed.set_thumbnail(url=user.avatar_bust_url)
    return embed


def build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title=f"🎮 {BRAND_PANEL_TITLE}",
        description=(
            "**ระบบตรวจสอบและค้นหาข้อมูลโปรไฟล์ผู้เล่น Roblox**\n"
            "ดึงข้อมูลสดจาก Roblox API: สถานะบัญชี, สถานะออนไลน์, วันที่สร้าง, เพื่อน และ Avatar\n\n"
            "📋 **วิธีการใช้งาน**\n"
            "• **วิธีที่ 1:** กดปุ่ม **`[ ▶ ค้นหาผู้เล่น Roblox ]`** ด้านล่าง เพื่อเปิดหน้าต่างกรอกชื่อ\n"
            "• **วิธีที่ 2:** พิมพ์ **Username** หรือ **User ID** ในห้องนี้ได้ทันที!\n\n"
            "📍 *ผลการค้นหาจะแสดงที่ห้องผลลัพธ์โดยอัตโนมัติ*"
        ),
        color=discord.Color(BRAND_COLOR)
    )
    return embed


class RobloxLookupModal(discord.ui.Modal, title="PAYOMBØYZ | 🔍 ค้นหาผู้เล่น Roblox"):
    username_input = discord.ui.TextInput(
        label="กรอก Username หรือ ID ผู้เล่น Roblox *",
        placeholder="เช่น Roblox หรือ 9361460324",
        min_length=1,
        max_length=60,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        query = self.username_input.value.strip()
        success, user, message = await RobloxService.lookup_player(query)

        if not success or not user:
            await interaction.followup.send(f"❌ **ค้นหาไม่สำเร็จ:** {message}", ephemeral=True)
            return

        embed = build_player_embed(user)
        view = discord.ui.View()
        view.add_item(
            discord.ui.Button(
                label="ดูโปรไฟล์บน Roblox",
                emoji="🔗",
                url=user.profile_url,
                style=discord.ButtonStyle.link
            )
        )

        result_channel = None
        if RESULT_CHANNEL_ID:
            try:
                ch_id = int(RESULT_CHANNEL_ID)
                result_channel = interaction.client.get_channel(ch_id)
                if not result_channel and interaction.guild:
                    result_channel = await interaction.guild.fetch_channel(ch_id)
            except Exception:
                result_channel = None

        if result_channel and hasattr(result_channel, "send"):
            try:
                requester_mention = interaction.user.mention
                msg = await result_channel.send(
                    content=f"🔎 ค้นหาโดย: {requester_mention}",
                    embed=embed,
                    view=view
                )
                await interaction.followup.send(
                    f"✅ ค้นหาข้อมูลผู้เล่น **`{user.username}`** สำเร็จ!\n"
                    f"📍 ผลลัพธ์ถูกส่งไปยังห้อง {result_channel.mention} เรียบร้อยแล้ว [คลิกดูข้อความ]({msg.jump_url})",
                    ephemeral=True
                )
                return
            except Exception:
                pass

        await interaction.followup.send(embed=embed, view=view, ephemeral=False)


class RobloxPanelView(discord.ui.View):
    """Persistent View for Roblox Lookup Panel"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="ค้นหาผู้เล่น Roblox",
        emoji="▶",
        style=discord.ButtonStyle.primary,
        custom_id="btn_roblox_lookup_panel"
    )
    async def btn_lookup_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RobloxLookupModal())
