import asyncio
import base64
import binascii
import datetime
import json
import math
import os
import re
import sqlite3
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import discord
import requests
from discord.ext import commands, tasks
from binance_payout import execute_binance_withdraw


WEBHOOK = ""
BANNER_URL = "https://i.ibb.co/7d2kTP0j/1000241330.png"
EASYSLIP_VERIFY_URL = "https://api.easyslip.com/v2/verify/bank"
EASYSLIP_QR_GENERATE_URL = "https://api.easyslip.com/v1/qr/generate"
TRUEMONEY_VERIFY_URL = "https://gift.truemoney.com/campaign/vouchers/{code}/verify"
TRUEMONEY_REDEEM_URL = "https://gift.truemoney.com/campaign/vouchers/{code}/redeem"
def load_local_env():
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


load_local_env()
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
PROJECT_NAME = os.getenv("PROJECT_NAME", "พยอมบอยเติมเงิน")
try:
    SHOP_CHANNEL = int(os.getenv("SHOP_CHANNEL_ID", "0"))
except ValueError:
    SHOP_CHANNEL = 0
try:
    DISCORD_GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
except ValueError:
    DISCORD_GUILD_ID = 0
EASYSLIP_API_KEY = os.getenv("EASYSLIP_API_KEY", "")
TRUEMONEY_PHONE = re.sub(r"\D", "", os.getenv("TRUEMONEY_PHONE", "062-362-4327"))
BANK_NAME = os.getenv("BANK_NAME", "ไทยพาณิชย์ (SCB)")
BANK_CODE = os.getenv("BANK_CODE", "014")
BANK_ACCOUNT_NUMBER = os.getenv("BANK_ACCOUNT_NUMBER", "422-145-5448")
BANK_ACCOUNT_NAME = os.getenv("BANK_ACCOUNT_NAME", "ธนากร เธียรจินดากุล")
PROMPTPAY_NATID = re.sub(r"\D", "", os.getenv("PROMPTPAY_NATID", ""))
PROMPTPAY_PHONE = re.sub(r"\D", "", os.getenv("PROMPTPAY_PHONE", os.getenv("PROMPTPAY_MSISDN", "")))
EASYSLIP_QR_TYPE = os.getenv("EASYSLIP_QR_TYPE", "PROMPTPAY").upper().strip()
KSHOP_REF1 = os.getenv("KSHOP_REF1", "").strip()
MAE_MANEE_REF1 = os.getenv("MAE_MANEE_REF1", "").strip()
TUNGNGERN_REF1 = os.getenv("TUNGNGERN_REF1", "").strip()
TUNGNGERN_MERCHANT_NAME = os.getenv("TUNGNGERN_MERCHANT_NAME", "").strip()
import shop_data as store

VIP_ROLE_ID = 1549536919892004985
VVIP_ROLE_ID = 1549785782330593330
AI_ROLE_ID = 1549535527756111892
ADMIN_ROLE_ID = 1549535328753164418
VERIFIED_ROLE_ID = 1549536757484101814

def init_db():
    store.init_db()


def get_shop_settings():
    return store.get_settings()


def current_topup_instructions(text):
    text = (text or "").strip()
    text = re.sub(r"เติมเครดิตด้วย(?:คำสั่ง)?\s*`?/topup`?[^\n]*", "กดปุ่มเติมเครดิตด้านล่างเพื่อเลือกช่องทางชำระเงิน", text, flags=re.IGNORECASE)
    text = re.sub(r"แล้วใช้คำสั่ง\s*`?/topup`?\s*พร้อมแนบรูปสลิป", "แล้วกดปุ่มแนบสลิปด้านล่าง", text, flags=re.IGNORECASE)
    return text


def save_shop_settings(values):
    store.save_settings(values)


def get_product_prices():
    return {product["product_id"]: product["price"] for product in store.list_products(active_only=True)}


CLOUD_WEB_URL = os.getenv("CLOUD_WEB_URL", "https://payomboyz.shop").rstrip("/")
CLOUD_SYNC_KEY = os.getenv("CLOUD_SYNC_KEY", "280342")


def get_cloud_sync_headers():
    return {
        "Content-Type": "application/json",
        "x-admin-sync-key": CLOUD_SYNC_KEY,
        "x-sync-key": CLOUD_SYNC_KEY,
        "x-admin-pin": CLOUD_SYNC_KEY,
        "x-shop-secret": CLOUD_SYNC_KEY,
        "Origin": "https://payomboyz.shop",
        "User-Agent": "PayomboyZ-Shop-Bot/2.0",
    }


def get_balance(user_id):
    """100% Authoritative lookup from Supabase Cloud Database (members table)"""
    return store.get_balance(user_id)


def credit_topup(user_id, amount, payment_ref):
    """Atomic topup processed directly against Supabase Cloud Database"""
    return store.credit_topup(user_id, amount, payment_ref)


def check_website_product_exists(product_id: str):
    """Check product existence against Supabase shop_products"""
    p = store.get_product(product_id)
    if p:
        return True, p["product_id"], "Verified"
    return False, product_id, f"ไม่พบสินค้า {product_id} ในฐานข้อมูลระบบ"


def add_key_with_website_sync(product_id: str, secret: str):
    """Add key directly to Supabase license_keys"""
    clean_secret = secret.strip()
    if not clean_secret:
        return False, "❌ คีย์สินค้าต้องไม่ว่างเปล่าครับ"

    exists, norm_id, msg = check_website_product_exists(product_id)
    if not exists:
        return False, f"❌ ไม่พบสินค้า '{product_id}' ในระบบร้านค้าครับ"

    try:
        res = store.add_key(product_id, clean_secret)
        if res:
            return True, f"✅ เพิ่มคีย์สำหรับ {product_id} เข้าสู่ Supabase Cloud เรียบร้อยแล้วครับ"
        return False, "⚠️ ไม่สามารถเพิ่มคีย์ได้"
    except Exception as e:
        return False, f"⚠️ เกิดข้อผิดพลาด: {e}"


def add_key(product_id, secret):
    success, msg = add_key_with_website_sync(product_id, secret)
    return success


def key_stock():
    """Retrieve live stock counts directly from Supabase license_keys"""
    return store.key_counts()


def verify_easyslip(image_bytes, filename, content_type, user_id):
    if not EASYSLIP_API_KEY:
        return None, "แอดมินยังไม่ได้ตั้งค่า EasySlip API Key ครับ"
    if len(image_bytes) > 4 * 1024 * 1024:
        return None, "ไฟล์สลิปต้องมีขนาดไม่เกิน 4 MB ครับ"
    if content_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        return None, "รองรับไฟล์ JPG, PNG, GIF หรือ WEBP เท่านั้นครับ"

    try:
        response = requests.post(
            EASYSLIP_VERIFY_URL,
            headers={"Authorization": f"Bearer {EASYSLIP_API_KEY}"},
            files={"image": (filename, image_bytes, content_type)},
            data={
                "checkDuplicate": "true",
                "matchAccount": "true",
                "remark": f"Discord user {user_id}",
            },
            timeout=30,
        )
        result = response.json()
        if response.status_code != 200 or not result.get("success"):
            error = result.get("error", {})
            return None, error.get("message", "EasySlip ตรวจสลิปไม่สำเร็จครับ")

        data = result.get("data", {})
        if data.get("isDuplicate"):
            return None, "สลิปนี้ถูกใช้งานแล้วครับ"
        if not data.get("matchedAccount"):
            return None, "EasySlip จับคู่ผู้รับในสลิปกับบัญชีร้านไม่ได้ครับ"
        # EasySlip's matchAccount validates the registered recipient. The QR is
        # PromptPay, so its slip may identify a PromptPay alias or another bank
        # instead of the shop's underlying SCB account number.

        raw_slip = data.get("rawSlip", {})
        payment_ref = raw_slip.get("transRef")
        amount = data.get("amountInSlip")
        if amount is None:
            amount = raw_slip.get("amount", {}).get("amount")
        amount = float(amount or 0)
        if not payment_ref or amount <= 0:
            return None, "ข้อมูลสลิปไม่ครบหรือยอดไม่ถูกต้องครับ"
        return {"amount": amount, "payment_ref": payment_ref}, "ok"
    except requests.RequestException:
        return None, "เชื่อมต่อ EasySlip ไม่สำเร็จ ลองใหม่หรือติดต่อแอดมินครับ"
    except (ValueError, KeyError, TypeError):
        return None, "อ่านผลตรวจสลิปจาก EasySlip ไม่สำเร็จครับ"


def generate_easyslip_qr(
    amount=None,
    qr_type=None,
    identifier=None,
    ref1=None,
    merchant_name=None,
):
    if not EASYSLIP_API_KEY:
        return None, "แอดมินยังไม่ได้ตั้งค่า EasySlip API Key ครับ"

    chosen_type = (qr_type or EASYSLIP_QR_TYPE or "PROMPTPAY").upper().strip()
    payload = {"type": chosen_type}

    if chosen_type == "PROMPTPAY":
        raw_id = identifier or PROMPTPAY_NATID or PROMPTPAY_PHONE
        clean_id = re.sub(r"\D", "", str(raw_id or ""))
        if len(clean_id) == 13:
            payload["natId"] = clean_id
        elif len(clean_id) == 10 and clean_id.startswith("0"):
            payload["msisdn"] = clean_id
        elif len(clean_id) == 15:
            payload["eWalletId"] = clean_id
        else:
            return None, "ตั้งค่า PromptPay ID ไม่ถูกต้อง (ต้องเป็นเบอร์มือถือ 10 หลัก, บัตร ปชช. 13 หลัก หรือ E-wallet 15 หลัก)"
    elif chosen_type == "KSHOP":
        ref = (ref1 or KSHOP_REF1).strip()
        if not ref:
            return None, "ยังไม่ได้ตั้งค่า Reference 1 สำหรับ K-Shop ครับ"
        payload["ref1"] = ref.upper()[:20]
    elif chosen_type == "MAE_MANEE":
        ref = (ref1 or MAE_MANEE_REF1).strip()
        if not ref:
            return None, "ยังไม่ได้ตั้งค่า Reference 1 สำหรับ แม่มณี ครับ"
        payload["ref1"] = ref.upper()[:20]
    elif chosen_type == "TUNGNGERN":
        ref = (ref1 or TUNGNGERN_REF1).strip()
        if not ref:
            return None, "ยังไม่ได้ตั้งค่า Reference 1 สำหรับ ถุงเงิน ครับ"
        payload["ref1"] = ref.upper()[:20]
        mname = (merchant_name or TUNGNGERN_MERCHANT_NAME).strip()
        if mname:
            payload["merchantName"] = mname[:25]
    else:
        return None, f"ไม่รองรับประเภท QR: {chosen_type} (รองรับ PROMPTPAY, KSHOP, MAE_MANEE, TUNGNGERN)"

    if amount is not None:
        try:
            val = round(float(amount), 2)
            if val <= 0:
                return None, "จำนวนเงินต้องมากกว่า 0 บาทครับ"
            payload["amount"] = val
        except (ValueError, TypeError):
            return None, "รูปแบบจำนวนเงินไม่ถูกต้องครับ"

    try:
        response = requests.post(
            EASYSLIP_QR_GENERATE_URL,
            headers={
                "Authorization": f"Bearer {EASYSLIP_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        try:
            result = response.json()
        except ValueError:
            return None, f"EasySlip ส่งข้อมูลตอบกลับไม่ถูกต้อง (HTTP {response.status_code})"

        if response.status_code != 200 or result.get("status") != 200:
            msg = result.get("message", "EasySlip สร้าง QR ไม่สำเร็จครับ")
            errors = result.get("data", {}).get("errors")
            if isinstance(errors, list) and errors:
                err_str = ", ".join(f"{e.get('field')}: {e.get('message')}" for e in errors)
                msg = f"{msg} ({err_str})"
            return None, msg

        data = result.get("data", {})
        image_b64 = data.get("image")
        if not image_b64:
            return None, "EasySlip ไม่ได้ส่งภาพ QR กลับมาครับ"

        image_bytes = base64.b64decode(image_b64, validate=True)
        return {
            "image_bytes": image_bytes,
            "payload": data.get("payload", ""),
            "mime": data.get("mime", "image/png"),
            "amount": payload.get("amount"),
            "type": chosen_type,
        }, "ok"
    except requests.RequestException:
        return None, "เชื่อมต่อ EasySlip เพื่อสร้าง QR ไม่สำเร็จครับ"
    except (ValueError, TypeError, KeyError, binascii.Error):
        return None, "อ่านภาพ QR จาก EasySlip ไม่สำเร็จครับ"


def generate_promptpay_qr(amount=None):
    res, status = generate_easyslip_qr(amount=amount)
    if status != "ok" or not res:
        return None, status
    return res["image_bytes"], "ok"


def extract_truemoney_code(link):
    try:
        parsed = urlparse(link.strip())
        if (
            parsed.scheme != "https"
            or parsed.hostname != "gift.truemoney.com"
            or parsed.path.rstrip("/") != "/campaign"
        ):
            return None
        code = parse_qs(parsed.query).get("v", [""])[0].strip()
        return code if re.fullmatch(r"[A-Za-z0-9_-]{8,128}", code) else None
    except (TypeError, ValueError):
        return None


def redeem_truemoney(link, phone):
    code = extract_truemoney_code(link)
    phone = re.sub(r"\D", "", str(phone))
    if not code:
        return None, "ลิงก์ซองต้องเป็น https://gift.truemoney.com/campaign/?v=... ครับ"
    if not re.fullmatch(r"0\d{9}", phone):
        return None, "เบอร์ TrueMoney ของร้านตั้งค่าไม่ถูกต้องครับ"

    encoded_code = quote(code, safe="")

    # =========================================================================
    # Strategy 1: Cloudflare Edge Gateway (Bypasses Datacenter & GeoIP WAF Blocks)
    # =========================================================================
    try:
        gw_url = f"https://tmn-angpao.pages.dev/api/{phone}/{encoded_code}"
        gw_res = requests.get(gw_url, timeout=10)
        if gw_res.status_code == 200:
            gw_data = gw_res.json()
            if gw_data.get("success") and str(gw_data.get("code")).upper() == "SUCCESS":
                d = gw_data.get("data") or {}
                amount = float(d.get("amount") or 0)
                owner = d.get("name") or "ผู้ส่งซอง"
                if amount > 0:
                    return {"amount": amount, "owner": owner, "code": code}, "ok"
        elif gw_res.status_code in (400, 404):
            try:
                gw_data = gw_res.json()
                err_code = str(gw_data.get("code") or "").upper()
                msg = gw_data.get("message") or ""
                if err_code == "VOUCHER_NOT_FOUND":
                    return None, "ไม่พบซองของขวัญนี้ หรือลิงก์ซองไม่ถูกต้องครับ"
                if err_code == "VOUCHER_OUT_OF_STOCK":
                    return None, "ซองของขวัญนี้ถูกกดรับครบแล้วครับ"
                if err_code == "VOUCHER_EXPIRED":
                    return None, "ซองของขวัญนี้หมดอายุแล้วครับ"
                if err_code == "CANNOT_GET_OWN_VOUCHER":
                    return None, "ไม่สามารถรับซองของเบอร์ตัวเองได้ครับ"
                if msg:
                    return None, msg
            except Exception:
                pass
    except Exception as gw_err:
        print(f"[TrueMoney Edge Gateway Warning] {gw_err}")

    # =========================================================================
    # Strategy 2: Direct TrueMoney Campaign API (Fallback with Mobile Fingerprint)
    # =========================================================================
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
            "Mobile/15E148 Safari/604.1"
        ),
        "Origin": "https://gift.truemoney.com",
        "Referer": f"https://gift.truemoney.com/campaign/?v={encoded_code}",
    }
    try:
        redeem_response = requests.post(
            TRUEMONEY_REDEEM_URL.format(code=encoded_code),
            headers=headers,
            json={"mobile": phone, "voucher_hash": code},
            timeout=12,
        )
        if redeem_response.status_code == 200:
            redeem_data = redeem_response.json()
            redeem_status = redeem_data.get("status", {})
            redeem_message = str(redeem_status.get("message") or "").lower()
            redeem_code = str(redeem_status.get("code") or "").upper()
            if redeem_message == "success" or redeem_code == "SUCCESS":
                redeemed_data = redeem_data.get("data", {})
                ticket = redeemed_data.get("my_ticket") or {}
                amount_value = ticket.get("amount_baht") or redeemed_data.get("amount_baht") or 0
                amount = float(amount_value)
                owner = (redeemed_data.get("owner_profile") or {}).get("full_name") or "ผู้ส่งซอง"
                if amount > 0:
                    return {"amount": amount, "owner": owner, "code": code}, "ok"
        elif redeem_response.status_code == 400:
            try:
                rdata = redeem_response.json()
                status = rdata.get("status", {})
                c = str(status.get("code") or "").upper()
                msg = status.get("message") or ""
                if c == "VOUCHER_NOT_FOUND":
                    return None, "ไม่พบซองของขวัญนี้ หรือลิงก์ซองไม่ถูกต้องครับ"
                if c == "VOUCHER_OUT_OF_STOCK":
                    return None, "ซองของขวัญนี้ถูกกดรับครบแล้วครับ"
                if c == "VOUCHER_EXPIRED":
                    return None, "ซองของขวัญนี้หมดอายุแล้วครับ"
                if c == "CANNOT_GET_OWN_VOUCHER":
                    return None, "ไม่สามารถรับซองของเบอร์ตัวเองได้ครับ"
                if msg:
                    return None, msg
            except Exception:
                pass
    except Exception as dir_err:
        print(f"[TrueMoney Direct API Warning] {dir_err}")

    return None, "ระบบ TrueMoney ขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้ง หรือติดต่อแอดมินครับ"

async def member_is_verified(interaction):
    """Allow all server members to interact with shop and check balances."""
    if interaction.guild is None:
        return False
    return True


async def require_verified(interaction):
    """Ensure member is in guild before interacting with shop items."""
    if interaction.guild is None:
        if not interaction.response.is_done():
            await interaction.response.send_message("ใช้ร้านได้จากในเซิร์ฟเวอร์เท่านั้นครับ", ephemeral=True)
        else:
            await interaction.followup.send("ใช้ร้านได้จากในเซิร์ฟเวอร์เท่านั้นครับ", ephemeral=True)
        return False
    return True


def is_admin(interaction):
    if interaction.guild is None:
        return False
    if interaction.guild.owner_id == interaction.user.id:
        return True
    permissions = getattr(interaction.user, "guild_permissions", None)
    has_server_admin = bool(
        permissions and (permissions.administrator or permissions.manage_guild)
    )
    has_configured_admin_role = any(
        role.id == ADMIN_ROLE_ID for role in getattr(interaction.user, "roles", ())
    )
    return has_server_admin or has_configured_admin_role


class AddKeyModal(discord.ui.Modal):
    secret = discord.ui.TextInput(label="คีย์สินค้า", max_length=500)

    def __init__(self, product):
        record = store.get_product(product)
        label = record["name"] if record else product
        super().__init__(title=f"เพิ่มคีย์สินค้า {label}")
        self.product = product

    async def on_submit(self, interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("ไม่มีสิทธิ์ใช้คำสั่งนี้ครับ", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        success, msg = await asyncio.to_thread(add_key_with_website_sync, self.product, self.secret.value.strip())
        await interaction.followup.send(msg, ephemeral=True)


class RemoveKeyModal(discord.ui.Modal):
    secret = discord.ui.TextInput(label="คีย์ที่ต้องการลบ", max_length=500)

    def __init__(self, product):
        super().__init__(title=f"ลบคีย์ที่ยังไม่ขาย {product}")
        self.product = product

    async def on_submit(self, interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("ไม่มีสิทธิ์ใช้คำสั่งนี้ครับ", ephemeral=True)
            return
        removed = await asyncio.to_thread(store.remove_key_by_secret, self.product, self.secret.value.strip())
        await interaction.response.send_message(
            "ลบคีย์จากคลังแล้วครับ" if removed else "ไม่พบคีย์ในคลัง หรือคีย์นี้ขายไปแล้วครับ",
            ephemeral=True,
        )


class CheckKeyModal(discord.ui.Modal, title="ตรวจสอบคีย์"):
    secret = discord.ui.TextInput(label="คีย์ที่ต้องการตรวจ", max_length=500)

    async def on_submit(self, interaction):
        if not await member_is_verified(interaction):
            await interaction.response.send_message("ต้องมียศยืนยันตัวตนก่อนครับ", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        raw_key = self.secret.value.strip()

        # 1. Check local SQLite store
        product_id = await asyncio.to_thread(store.check_key, interaction.user.id, raw_key)
        if product_id:
            product = await asyncio.to_thread(store.get_product, product_id)
            name = product["name"] if product else product_id
            await interaction.followup.send(f"✅ คีย์นี้ถูกต้องและเป็นสินค้า **{name}** ของคุณ", ephemeral=True)
            return

        # 2. Check Cloud Supabase PostgreSQL public.license_keys
        try:
            url = "https://payomboyzcreative.online/api/v1/shop"
            r = await asyncio.to_thread(
                requests.post,
                url,
                json={"action": "check", "key": raw_key},
                headers={"x-admin-sync-key": CLOUD_SYNC_KEY},
                timeout=4.0
            )
            if r.status_code == 200:
                kdata = r.json().get("key", {})
                role = kdata.get("role", "VIP")
                status = kdata.get("status", "active")
                exp = kdata.get("expires_at")
                exp_str = f" · หมดอายุ: `{exp[:10]}`" if exp else " · ถาวรตลอดชีพ"
                msg = (
                    f"✅ คีย์ถูกต้องในระบบ Cloud Whitelist!\n"
                    f"📌 **แพ็กเกจ:** `{role}`\n"
                    f"📊 **สถานะ:** `{status}`{exp_str}\n"
                    f"🌐 ใช้งานสคริปต์ได้ทันทีที่ https://payomboyzcreative.online/"
                )
                await interaction.followup.send(msg, ephemeral=True)
                return
        except Exception as e:
            print(f"[CheckKey Cloud Error] {e}")

        await interaction.followup.send("ไม่พบคีย์นี้ในระบบหรือบัญชีของคุณ กรุณาตรวจสอบตัวอักษรอีกครั้งครับ", ephemeral=True)


async def credit_topup_and_reply(interaction, amount, payment_ref, method, legacy_ref=None, expected_amount=None):
    if legacy_ref and await asyncio.to_thread(store.topup_exists, legacy_ref):
        await interaction.followup.send(
            "⚠️ รายการชำระเงินนี้ถูกบันทึกแล้ว ไม่เพิ่มเครดิตซ้ำครับ",
            ephemeral=True,
        )
        return
    try:
        saved = await asyncio.to_thread(
            credit_topup, interaction.user.id, amount, payment_ref
        )
    except Exception as e:
        print(f'[credit_topup error] {e}')
        print(
            f"CRITICAL: payment received but database credit failed; "
            f"method={method}, user_id={interaction.user.id}"
        )
        await interaction.followup.send(
            "⚠️ รับชำระสำเร็จแต่บันทึกเครดิตไม่สำเร็จ กรุณาติดต่อแอดมินพร้อมแจ้ง Discord ID ครับ",
            ephemeral=True,
        )
        return
    if not saved:
        await interaction.followup.send(
            "⚠️ รายการชำระเงินนี้ถูกบันทึกแล้ว ไม่เพิ่มเครดิตซ้ำครับ",
            ephemeral=True,
        )
        return
    balance = await asyncio.to_thread(get_balance, interaction.user.id)

    note = ""
    if expected_amount is not None and abs(amount - expected_amount) > 0.01:
        note = f"\n*(ยอดในสลิป {amount:,.2f}฿ แตกต่างจากยอดที่ล็อคไว้ {expected_amount:,.2f}฿ — ระบบเติมตามยอดสลิปจริง)*"

    embed = discord.Embed(
        title="✅ เติมเครดิตสำเร็จ",
        description=(
            f"🎉 ได้รับเครดิต: **+{amount:,.2f} บาท**{note}\n"
            f"💰 เครดิตคงเหลือปัจจุบัน: **{balance:,.2f} บาท**"
        ),
        color=0x2ECC71,
    )
    embed.set_footer(text=f"เลขอ้างอิง: {payment_ref}")
    await interaction.followup.send(embed=embed, ephemeral=True)


async def process_slip_topup(interaction, slip, expected_amount=None):
    if interaction.guild is None:
        msg = "กรุณาเติมเครดิตจากแผงร้านในเซิร์ฟเวอร์ครับ"
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
        return

    # Flexible size check
    slip_size = getattr(slip, "size", 0)
    if slip_size > 6 * 1024 * 1024:
        msg = "ไฟล์สลิปต้องมีขนาดไม่เกิน 6 MB ครับ"
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
        return

    ct = (getattr(slip, "content_type", "") or "").lower()
    fn = (getattr(slip, "filename", "") or "").lower()
    is_img = any(ct.startswith(x) for x in ["image/", "application/octet-stream"]) or any(fn.endswith(x) for x in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"])
    if not is_img:
        msg = "กรุณาแนบสลิปเป็นรูปภาพ (JPG, PNG, WEBP) ครับ"
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    try:
        image_bytes = await slip.read()
    except Exception as e:
        await interaction.followup.send(f"ดาวน์โหลดรูปสลิปไม่สำเร็จ: {e}", ephemeral=True)
        return

    try:
        result, status = await asyncio.to_thread(
            verify_easyslip,
            image_bytes,
            getattr(slip, "filename", "slip.jpg"),
            ct or "image/jpeg",
            interaction.user.id,
        )
    except Exception as e:
        print(f"[EasySlip Verification Exception] {e}")
        await interaction.followup.send(f"❌ ระบบตรวจสลิปขัดข้องชั่วคราว: {e}", ephemeral=True)
        return

    if status != "ok":
        await interaction.followup.send(f"❌ ตรวจสลิปไม่ผ่าน: {status}", ephemeral=True)
        return

    reference = str(result["payment_ref"])
    payment_ref = f"bank:{reference}"
    try:
        await credit_topup_and_reply(
            interaction,
            result["amount"],
            payment_ref,
            "bank_slip",
            legacy_ref=reference,
            expected_amount=expected_amount,
        )
    except Exception as e:
        print(f"[Credit Topup Exception] {e}")
        await interaction.followup.send(f"⚠️ ยอดเงินเข้าแล้วแต่เกิดข้อผิดพลาดในการบันทึกเครดิต: {e}", ephemeral=True)

class SlipUploadModal(discord.ui.Modal):
    def __init__(self, expected_amount=None):
        super().__init__(title="แนบสลิปโอนเงิน")
        self.expected_amount = expected_amount
        self.upload = discord.ui.FileUpload(
            required=True, min_values=1, max_values=1
        )
        self.add_item(
            discord.ui.Label(
                text="รูปสลิป",
                description="JPG, PNG, GIF หรือ WEBP ขนาดไม่เกิน 4 MB",
                component=self.upload,
            )
        )

    async def on_submit(self, interaction):
        attachments = self.upload.values
        if not attachments:
            await interaction.response.send_message(
                "กรุณาแนบรูปสลิปก่อนส่งครับ", ephemeral=True
            )
            return
        await process_slip_topup(interaction, attachments[0], expected_amount=self.expected_amount)


class SlipUploadView(discord.ui.View):
    def __init__(self, expected_amount=None):
        super().__init__(timeout=None)
        self.expected_amount = expected_amount

    @discord.ui.button(label="แนบสลิปเพื่อตรวจสอบ", emoji="🧾", style=discord.ButtonStyle.success)
    async def upload_slip(self, interaction, button):
        await interaction.response.send_modal(SlipUploadModal(expected_amount=self.expected_amount))


class PromptPayAmountModal(discord.ui.Modal, title="ระบุยอดเงินที่ต้องการเติม"):
    amount_input = discord.ui.TextInput(
        label="จำนวนเงิน (บาท) เพื่อล็อคยอดใน QR",
        placeholder="เช่น 50, 100, 150 หรือ 299",
        min_length=1,
        max_length=10,
        required=True,
    )

    def __init__(self, default_amount: float | None = None):
        super().__init__()
        if default_amount is not None and default_amount > 0:
            self.amount_input.default = f"{default_amount:.2f}".rstrip("0").rstrip(".")

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.amount_input.value.strip().replace(",", "")
        try:
            amount = float(raw)
        except ValueError:
            await interaction.response.send_message(
                "❌ กรุณากรอกจำนวนเงินเป็นตัวเลข เช่น 50, 100 หรือ 150.50 ครับ",
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message("❌ จำนวนเงินต้องมากกว่า 0 บาทครับ", ephemeral=True)
            return
        if amount > 100000:
            await interaction.response.send_message("❌ ยอดเติมเงินต่อครั้งต้องไม่เกิน 100,000 บาทครับ", ephemeral=True)
            return

        await send_locked_qr_message(interaction, amount)


class LockedQRView(discord.ui.View):
    def __init__(self, amount: float):
        super().__init__(timeout=None)
        self.amount = amount

    @discord.ui.button(
        label="แนบสลิปเพื่อตรวจสอบ",
        emoji="🧾",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def upload_slip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SlipUploadModal(expected_amount=self.amount))

    @discord.ui.button(
        label="เปลี่ยนยอดเงิน",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def change_amount(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PromptPayAmountModal(default_amount=self.amount))

    @discord.ui.button(
        label="ดูเลขบัญชี SCB โอนตรง",
        emoji="🏦",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def show_bank(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🏦 บัญชีธนาคารสำหรับโอนตรง",
            description="หากไม่สะดวกสแกน QR Code สามารถโอนเข้าบัญชีด้านล่างแล้วแนบสลิปได้เช่นกันครับ",
            color=0x4E5D94,
        )
        embed.add_field(name="ธนาคาร", value=BANK_NAME, inline=True)
        embed.add_field(name="เลขบัญชี", value=f"`{BANK_ACCOUNT_NUMBER}`", inline=True)
        embed.add_field(name="ชื่อบัญชี", value=BANK_ACCOUNT_NAME, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def send_locked_qr_message(interaction: discord.Interaction, amount: float):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)

    result, status = await asyncio.to_thread(generate_easyslip_qr, amount=amount)
    if status != "ok" or not result:
        err_embed = discord.Embed(
            title="⚠️ สร้าง QR Code ไม่สำเร็จ",
            description=(
                f"เกิดข้อผิดพลาด: **{status}**\n\n"
                f"คุณยังสามารถโอนเข้าเลขบัญชีด้านล่างแล้วแนบสลิปเพื่อเติมเครดิตได้ตามปกติครับ"
            ),
            color=0xE74C3C,
        )
        err_embed.add_field(name="ธนาคาร", value=BANK_NAME, inline=True)
        err_embed.add_field(name="เลขบัญชี", value=f"`{BANK_ACCOUNT_NUMBER}`", inline=True)
        err_embed.add_field(name="ชื่อบัญชี", value=BANK_ACCOUNT_NAME, inline=False)
        await interaction.followup.send(
            embed=err_embed,
            view=SlipUploadView(),
            ephemeral=True,
        )
        return

    qr_bytes = result["image_bytes"]
    filename = f"qr_{int(amount * 100)}.png"

    embed = discord.Embed(
        title=f"🧾 สแกน QR ชำระเงิน (ล็อคยอด {amount:,.2f} บาท)",
        description=(
            f"✨ **ระบบล็อคยอดเงินเรียบร้อยแล้ว**\n"
            f"เมื่อเปิดแอพธนาคารสแกน QR Code ด้านล่าง ยอดจะขึ้น **{amount:,.2f} บาท** อัตโนมัติ โดยไม่ต้องพิมพ์ยอดเอง\n\n"
            f"📋 **ขั้นตอนการชำระเงิน:**\n"
            f"1. บันทึกรูปภาพ หรือเปิดแอพธนาคารสแกน QR Code ด้านล่าง\n"
            f"2. ตรวจสอบชื่อบัญชีผู้รับ **{BANK_ACCOUNT_NAME}** และกดยืนยันการโอน\n"
            f"3. เมื่อโอนสำเร็จ กดปุ่ม **'แนบสลิปเพื่อตรวจสอบ'** ด้านล่างได้ทันที\n"
            f"*(ระบบตรวจสลิปอัตโนมัติผ่าน EasySlip และเพิ่มเครดิตให้ทันทีครับ)*"
        ),
        color=0x00A86B,
    )
    embed.add_field(name="💰 ยอดชำระที่ต้องโอน", value=f"```fix\n{amount:,.2f} บาท\n```", inline=False)
    embed.add_field(name="👤 ชื่อบัญชีผู้รับ", value=f"**{BANK_ACCOUNT_NAME}**", inline=True)
    embed.add_field(name="🏦 ธนาคาร / ช่องทาง", value=BANK_NAME, inline=True)
    embed.set_image(url=f"attachment://{filename}")
    embed.set_footer(text="EasySlip Auto-Verification · ไม่เสียค่าธรรมเนียม · ใช้งานได้ตลอด 24 ชม.")

    await interaction.followup.send(
        embed=embed,
        file=discord.File(BytesIO(qr_bytes), filename=filename),
        view=LockedQRView(amount=amount),
        ephemeral=True,
    )


class TrueMoneyTopupModal(discord.ui.Modal, title="เติมเครดิตด้วยซอง TrueMoney"):
    voucher_link = discord.ui.TextInput(
        label="ลิงก์ซอง TrueMoney",
        placeholder="https://gift.truemoney.com/campaign/?v=...",
        max_length=300,
    )

    async def on_submit(self, interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "กรุณาเติมเครดิตจากแผงร้านในเซิร์ฟเวอร์ครับ", ephemeral=True
            )
            return
        code = extract_truemoney_code(self.voucher_link.value)
        if not code:
            await interaction.response.send_message(
                "ลิงก์ไม่ถูกต้อง ใช้ลิงก์จาก gift.truemoney.com เท่านั้นครับ",
                ephemeral=True,
            )
            return

        payment_ref = f"truemoney:{code}"
        already_recorded = await asyncio.to_thread(store.topup_exists, payment_ref)
        if not already_recorded:
            already_recorded = await asyncio.to_thread(store.topup_exists, code)
        if already_recorded:
            await interaction.response.send_message(
                "ซองนี้ถูกบันทึกไปแล้ว ไม่สามารถเติมซ้ำได้ครับ", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        result, status = await asyncio.to_thread(
            redeem_truemoney, self.voucher_link.value, TRUEMONEY_PHONE
        )
        if status != "ok":
            await interaction.followup.send(
                f"รับซองไม่สำเร็จ: {status}", ephemeral=True
            )
            return
        await credit_topup_and_reply(
            interaction,
            result["amount"],
            payment_ref,
            "truemoney",
            legacy_ref=code,
        )


EMOJI_SNOWFLAKE_MAP = {
    "emoji_16": 1564046478949879988,
    "scb": 1564046023469563944,
    "truemoney": 1564046207536463922,
    "halal_coin_bsc_usdt": 1564038716962504905,
    "halal_coin_tron_usdt": 1564038731235860571,
    "halal_coin_ethereum_usdt": 1564038738516905984,
    "halal_coin_litecoin": 1564038744875602040,
    "rules": 1564038770729291776,
    "time": 1564047534157074483,
}

def resolve_button_emoji(target_name: str, fallback_unicode: str):
    """Safely resolves an emoji for discord.ui.Button from bot.emojis cache or verified guild emoji ID."""
    try:
        clean_target = target_name.strip(':').split('~')[0].lower().replace('-', '_')
        for em in bot.emojis:
            em_name_clean = em.name.lower().replace('-', '_')
            if em_name_clean == clean_target or clean_target in em_name_clean:
                return em
        if clean_target in EMOJI_SNOWFLAKE_MAP:
            is_anim = clean_target == "time"
            return discord.PartialEmoji(name=target_name.strip(':').split('~')[0], id=EMOJI_SNOWFLAKE_MAP[clean_target], animated=is_anim)
    except Exception:
        pass
    return fallback_unicode


async def fetch_live_crypto_rates():
    """Fetches real-time market rates from Bitkub / Binance (same as CryptoPayment engine)."""
    usdt_thb = 34.50
    try:
        r = await asyncio.to_thread(requests.get, "https://api.bitkub.com/api/market/ticker?sym=THB_USDT", timeout=4)
        if r.status_code == 200:
            last_rate = r.json().get("THB_USDT", {}).get("last")
            if last_rate:
                usdt_thb = float(last_rate)
    except Exception:
        try:
            r = await asyncio.to_thread(requests.get, "https://api.binance.com/api/v3/ticker/price?symbol=USDTTHB", timeout=3)
            if r.status_code == 200:
                p = r.json().get("price")
                if p:
                    usdt_thb = float(p)
        except Exception:
            pass

    ltc_thb = 1900.00
    try:
        r = await asyncio.to_thread(requests.get, "https://api.binance.com/api/v3/ticker/price?symbol=LTCUSDT", timeout=3)
        if r.status_code == 200:
            ltc_usd = float(r.json().get("price", 0))
            if ltc_usd > 0:
                ltc_thb = round(ltc_usd * usdt_thb, 2)
    except Exception:
        pass

    return usdt_thb, ltc_thb


def verify_onchain_bsc_tx(tx_hash: str, receiving_wallet: str = "0xc7dd6ed5b2a797b0f7b3d736e59101823b15758d"):
    """Direct On-Chain BSC RPC fallback validator for BEP-20 USDT deposit."""
    clean_tx = tx_hash.strip()
    if not clean_tx.startswith("0x"):
        clean_tx = "0x" + clean_tx
    rpc_url = os.getenv("BSC_RPC_URL", "https://bsc-dataseed1.binance.org")
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getTransactionReceipt",
        "params": [clean_tx],
        "id": 1
    }
    try:
        resp = requests.post(rpc_url, json=payload, timeout=8)
        if resp.status_code != 200:
            return False, 0.0, "ไม่สามารถเชื่อมต่อ RPC บล็อกเชนได้"
        res_data = resp.json().get("result")
        if not res_data:
            return False, 0.0, "ไม่พบ Transaction Hash บน BSC หรือธุรกรรมยังไม่ได้รับการยืนยันบล็อก"
        if res_data.get("status") != "0x1":
            return False, 0.0, "ธุรกรรมนี้ล้มเหลว (Failed / Reverted) บนบล็อกเชน"

        valid_addrs = {
            "0xc7dd6ed5b2a797b0f7b3d736e59101823b15758d".lower().replace("0x", "").zfill(64),
            "0xEEa103Fc2f0c03a63C95499609Bf8713B8f81BA2".lower().replace("0x", "").zfill(64)
        }
        usdt_contract = "0x55d398326f99059ff775485246999027b3197955".lower()
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

        for log in res_data.get("logs", []):
            contract = log.get("address", "").lower()
            topics = log.get("topics", [])
            if contract == usdt_contract and len(topics) >= 3 and topics[0].lower() == transfer_topic:
                to_topic = topics[2].lower().replace("0x", "").zfill(64)
                if to_topic in valid_addrs:
                    raw_val = int(log.get("data", "0x0"), 16)
                    usdt_amount = round(raw_val / (10 ** 18), 4)
                    return True, usdt_amount, None
        return False, 0.0, "ไม่พบรายการโอน USDT ไปยังกระเป๋าของร้าน กรุณาตรวจ Address และเหรียญที่โอน"
    except Exception as e:
        return False, 0.0, f"เกิดข้อผิดพลาดในการตรวจสอบบล็อก: {e}"


class TopupMethodView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.promptpay_locked.emoji = resolve_button_emoji("emoji_16", "📱")
        self.bank_transfer.emoji = resolve_button_emoji("SCB", "🏦")
        self.truemoney.emoji = resolve_button_emoji("Truemoney", "💚")
        self.crypto_deposit.emoji = resolve_button_emoji("halal_coin_bsc_usdt", "🪙")

    @discord.ui.button(
        label="PromptPay QR (ล็อคยอดเงิน)",
        emoji="📱",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def promptpay_locked(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PromptPayAmountModal())

    @discord.ui.button(
        label="โอนผ่านบัญชี SCB / QR ปกติ",
        emoji="🏦",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def bank_transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        settings = await asyncio.to_thread(get_shop_settings)
        instructions = current_topup_instructions(settings.get("panel_description", ""))
        if not instructions:
            instructions = "สแกน QR PromptPay แล้วใส่ยอดที่ต้องการ หรือโอนเข้าบัญชี SCB ด้านล่างก็ได้ครับ"
        qr_image, qr_status = await asyncio.to_thread(generate_promptpay_qr)
        if qr_status != "ok":
            instructions += "\n\nตอนนี้สร้าง QR ไม่ได้ ใช้โอนเข้าบัญชี SCB ด้านล่างแทนได้ครับ"
        embed = discord.Embed(
            title="เติมเครดิตผ่าน PromptPay QR / โอนเข้าบัญชี SCB",
            description=(
                f"{instructions}\n\nแนบสลิปฉบับจริงหลังโอน "
                "ระบบจะตรวจผู้รับ ยอดเงิน และรายการซ้ำก่อนเพิ่มเครดิตครับ"
            ),
            color=0x2ECC71,
        )
        embed.add_field(name="ธนาคาร", value=BANK_NAME, inline=True)
        embed.add_field(name="เลขบัญชี", value=f"`{BANK_ACCOUNT_NUMBER}`", inline=True)
        embed.add_field(name="ชื่อบัญชี", value=BANK_ACCOUNT_NAME, inline=False)
        if qr_image:
            filename = "promptpay-qr.png"
            embed.set_image(url=f"attachment://{filename}")
            await interaction.followup.send(
                embed=embed,
                file=discord.File(BytesIO(qr_image), filename=filename),
                view=SlipUploadView(),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=embed,
                view=SlipUploadView(),
                ephemeral=True,
            )

    @discord.ui.button(
        label="ซอง TrueMoney",
        emoji="💚",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def truemoney(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TrueMoneyTopupModal())

    @discord.ui.button(
        label="เติมเงินผ่าน Crypto (USDT / LTC)",
        emoji="🪙",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def crypto_deposit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        usdt_rate, ltc_rate = await fetch_live_crypto_rates()

        embed = discord.Embed(
            title="🪙 เติมเครดิตผ่าน Crypto (USDT / LTC)",
            description=(
                "**ฝากเหรียญเข้า Binance Treasury (Official)**\n"
                "ระบบจะตรวจสอบบล็อก On-chain และคำนวณเครดิตเป็นเงินบาทเข้ากระเป๋าอัตโนมัติครับ\n\n"
                f"• **ขั้นต่ำการฝาก:** `6.00 USDT` (≈ ฿{6.0 * usdt_rate:,.2f})\n"
                f"• **อัตราแลกเปลี่ยน Real-time:** `1 USDT ≈ ฿{usdt_rate:.2f}` | `1 LTC ≈ ฿{ltc_rate:,.2f}`\n"
                "• **Network ที่รองรับ:** BSC (BNB Smart Chain / BEP-20) [แนะนำ] หรือ Polygon"
            ),
            color=0x00FF88,
        )
        embed.add_field(
            name="📍 Binance Treasury Deposit Address (BSC / BEP-20)",
            value="`0xc7dd6ed5b2a797b0f7b3d736e59101823b15758d`",
            inline=False,
        )
        embed.add_field(
            name="ℹ️ ขั้นตอนการเติม",
            value=(
                "1. โอนเหรียญ USDT (ขั้นต่ำ 6.00 USDT) ไปยัง Address ด้านบน\n"
                "2. เมื่อโอนสำเร็จแล้ว ให้กดปุ่ม **[ ⚡ แจ้งรหัสธุรกรรม (TXID) ]** ด้านล่าง\n"
                "3. นำ Transaction Hash มาวาง ระบบจะตรวจบล็อกและเพิ่มเครดิตเป็นเงินบาททันที"
            ),
            inline=False,
        )
        embed.set_image(url="https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=0xc7dd6ed5b2a797b0f7b3d736e59101823b15758d")
        embed.set_footer(text="PAYOMBØYZ CRYPTO SECURITY GATE • ON-CHAIN AUTO VERIFIED")

        view = CryptoDepositActionView(rate=usdt_rate)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class CryptoTxidModal(discord.ui.Modal, title="⚡ ยืนยันรายการโอน Crypto (TXID)"):
    tx_hash = discord.ui.TextInput(
        label="Transaction Hash / TXID",
        placeholder="เช่น 0x9a8b7c6d5e4f3a2b1c...",
        min_length=10,
        max_length=120,
        required=True,
    )

    def __init__(self, rate: float):
        super().__init__()
        self.rate = rate

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        clean_tx = self.tx_hash.value.strip()

        payment_ref = f"crypto:{clean_tx.lower()}"
        if await asyncio.to_thread(store.topup_exists, payment_ref):
            await interaction.followup.send("⚠️ รายการโอนนี้ (TXID) ถูกนำมาเติมเครดิตแล้ว ไม่สามารถใช้ซ้ำได้ครับ", ephemeral=True)
            return

        usdt_amount = 0.0
        verified = False
        error_msg = None

        # 1. Primary engine: Isolated Signing Vault API
        vault_url = "https://sn9n9cvijp.apps.bot-hosting.cloud/api/v1/verify-deposit"
        payload = {
            "txHash": clean_tx,
            "platform": "Discord Bot",
            "username": f"{interaction.user.name} ({interaction.user.id})"
        }
        headers = {
            "Content-Type": "application/json",
            "x-vault-token": os.getenv("VAULT_AUTH_TOKEN", "pbz_vault_9f82c47ab1e56304d7c81a2f90be6531")
        }

        try:
            res = await asyncio.to_thread(requests.post, vault_url, json=payload, headers=headers, timeout=12)
            if res.status_code == 200:
                data = res.json()
                if data.get("verified"):
                    verified = True
                    usdt_amount = float(data.get("amountUSDT", 0))
                else:
                    error_msg = data.get("error")
        except Exception as e:
            error_msg = str(e)

        # 2. Dual-Engine Fallback: Direct on-chain BSC RPC verification
        if not verified and clean_tx.startswith("0x"):
            ok, bsc_amount, bsc_err = await asyncio.to_thread(verify_onchain_bsc_tx, clean_tx)
            if ok:
                verified = True
                usdt_amount = bsc_amount
                error_msg = None
            elif not error_msg:
                error_msg = bsc_err

        if not verified or usdt_amount <= 0:
            msg = error_msg or "ไม่สามารถยืนยันธุรกรรม On-Chain ได้ กรุณาตรวจสอบ TXID หรือรอให้บล็อกคอนเฟิร์มสักครู่ครับ"
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            return

        if usdt_amount < 6.0:
            await interaction.followup.send(f"❌ ยอดฝากคือ {usdt_amount:.2f} USDT ซึ่งต่ำกว่าขั้นต่ำ 6.00 USDT ครับ", ephemeral=True)
            return

        thb_amount = round(usdt_amount * self.rate, 2)

        try:
            saved = await asyncio.to_thread(credit_topup, interaction.user.id, thb_amount, payment_ref)
        except Exception as e:
            await interaction.followup.send(f"⚠️ ยืนยันบล็อกสำเร็จ แต่บันทึกเครดิตผิดพลาด: {e}", ephemeral=True)
            return

        if not saved:
            await interaction.followup.send("⚠️ รายการโอนนี้ (TXID) ถูกนำมาเติมเครดิตแล้ว ไม่สามารถใช้ซ้ำได้ครับ", ephemeral=True)
            return

        new_balance = await asyncio.to_thread(get_balance, interaction.user.id)

        embed = discord.Embed(
            title="🎉 เติมเงินผ่าน Crypto สำเร็จ!",
            description=(
                f"ระบบตรวจสอบ On-Chain ยืนยันยอดเข้ากระเป๋าเรียบร้อยแล้ว\n\n"
                f"• **เหรียญที่โอน:** `{usdt_amount:.2f} USDT`\n"
                f"• **อัตราแลกเปลี่ยน Real-time:** `฿{self.rate:.2f}` / USDT\n"
                f"• **เครดิตที่ได้รับ:** `+฿{thb_amount:,.2f}`\n"
                f"• **เครดิตคงเหลือทั้งหมด:** `฿{new_balance:,.2f}`\n\n"
                f"• **TXID:** [`{clean_tx[:16]}...`](https://bscscan.com/tx/{clean_tx})"
            ),
            color=0x2ECC71,
        )
        embed.set_footer(text="PAYOMBØYZ CRYPTO GATEWAY • ON-CHAIN AUTO VERIFIED")
        await interaction.followup.send(embed=embed, ephemeral=True)


class CryptoDepositActionView(discord.ui.View):
    def __init__(self, rate: float):
        super().__init__(timeout=None)
        self.rate = rate

    @discord.ui.button(
        label="⚡ แจ้งรหัสธุรกรรม (TXID)",
        emoji="📝",
        style=discord.ButtonStyle.success,
    )
    async def submit_txid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CryptoTxidModal(rate=self.rate))


class CryptoSlipActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="ส่งสลิปทาง DM บอท (แนะนำ)",
        emoji="📩",
        style=discord.ButtonStyle.success,
        custom_id="btn_topup_dm_slip",
    )
    async def dm_slip(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            dm = await interaction.user.create_dm()
            embed = discord.Embed(
                title="📸 แชทส่งสลิปโอนเงิน (PayomboyZ Crypto Exchange)",
                description=(
                    f"สวัสดีครับคุณ <@{interaction.user.id}>!\n\n"
                    "**กรุณากดแนบรูปภาพสลิปโอนเงินส่งเข้ามาในช่องแชทส่วนตัวนี้ได้เลยครับ**\n"
                    "ระบบ EasySlip จะสแกน QR Code บนสลิปและเพิ่มเครดิตเข้ากระเป๋าของคุณทันทีภายใน 3 วินาที!\n\n"
                    "*(ช่องทางนี้ปลอดภัย 100% สลิปจะไม่ถูกเปิดเผยในเซิร์ฟเวอร์)*"
                ),
                color=0x00FF88,
            )
            embed.set_footer(text="EasySlip Instant Verification 24/7")
            await dm.send(embed=embed)
            await interaction.response.send_message("✅ บอทได้ส่งข้อความทักไปใน **แชทส่วนตัว (DM)** ของคุณเรียบร้อยแล้ว! กรุณาเปิดหน้าแชทกับบอทแล้วส่งรูปภาพสลิปได้เลยครับ", ephemeral=True)
        except Exception:
            await interaction.response.send_message("⚠️ ไม่สามารถส่งข้อความไปทาง DM ได้ เนื่องจากคุณปิดรับข้อความส่วนตัว กรุณาเปิดรับ DM หรือใช้คำสั่ง `/slip` เพื่อแนบรูปสลิปโดยตรงได้เลยครับ", ephemeral=True)

    @discord.ui.button(
        label="วิธีใช้คำสั่ง /slip",
        emoji="⌨️",
        style=discord.ButtonStyle.secondary,
        custom_id="btn_guide_slash_slip",
    )
    async def guide_slip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "📌 **วิธีแนบสลิปผ่านคำสั่ง `/slip`:**\n"
            "1. พิมพ์คำสั่ง `/slip` ในช่องแชทของเซิร์ฟเวอร์\n"
            "2. จะมีช่อง `image` ปรากฏขึ้นมา ให้กดเลือกไฟล์รูปภาพสลิปจากมือถือหรือคอมพิวเตอร์ของคุณ\n"
            "3. กด Enter ส่งคำสั่งได้ทันที ระบบจะตรวจสอบและเพิ่มเครดิตให้อัตโนมัติใน 3 วินาที (คำสั่งนี้จะเห็นเฉพาะคุณเท่านั้น ไม่มีใครในห้องเห็นสลิปของคุณ)",
            ephemeral=True,
        )


class CryptoExchangeAssetModal(discord.ui.Modal):
    def __init__(self, asset_id: str, label: str, network: str, placeholder: str):
        super().__init__(title=f"🔄 แลกเหรียญ {label}")
        self.asset_id = asset_id
        self.label = label
        self.network = network

        self.address_input = discord.ui.TextInput(
            label=f"ที่อยู่กระเป๋า {label} ปลายทาง",
            placeholder=placeholder,
            style=discord.TextStyle.short,
            required=True,
            custom_id="input_address",
        )
        self.add_item(self.address_input)

        symbol = "LTC" if "LTC" in asset_id else "USDT"
        self.amount_input = discord.ui.TextInput(
            label=f"ระบุยอดเงิน (บาท) หรือยอดเหรียญ ({symbol})",
            placeholder=f"ใส่ยอดบาท เช่น 50, 100 หรือระบุเหรียญ เช่น 0.05 หรือพิมพ์ all เพื่อแลกหมด",
            style=discord.TextStyle.short,
            required=True,
            custom_id="input_amount",
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        addr = self.address_input.value.strip()
        amt_str = self.amount_input.value.strip().upper()

        usdt_rate, ltc_rate = await fetch_live_crypto_rates()
        rate = ltc_rate if "LTC" in self.asset_id else usdt_rate
        symbol = "LTC" if "LTC" in self.asset_id else "USDT"

        bal = await asyncio.to_thread(get_balance, interaction.user.id)
        if bal <= 0:
            await interaction.followup.send("❌ คุณไม่มีเครดิตในกระเป๋าครับ กรุณากดปุ่มเติมเครดิตก่อนทำรายการ", ephemeral=True)
            return

        clean_amt = amt_str.replace(",", "").strip()
        try:
            if clean_amt.lower() in ("all", "max", "ทั้งหมด", "หมด"):
                thb_req = bal
                crypto_amount = round(thb_req / rate, 4 if symbol == "LTC" else 2)
            elif clean_amt.endswith(("LTC", "USDT", "COIN")):
                val = float(re.sub(r"[^0-9.]", "", clean_amt))
                crypto_amount = val
                thb_req = round(crypto_amount * rate, 2)
            elif clean_amt.endswith(("B", "THB", "บาท")):
                thb_req = float(re.sub(r"[^0-9.]", "", clean_amt))
                crypto_amount = round(thb_req / rate, 4 if symbol == "LTC" else 2)
            else:
                val = float(re.sub(r"[^0-9.]", "", clean_amt))
                if val < 1.0:
                    crypto_amount = val
                    thb_req = round(crypto_amount * rate, 2)
                elif symbol == "LTC":
                    # For LTC (rate ~2,000 THB), user entering >= 1.0 is specifying THB
                    thb_req = val
                    crypto_amount = round(thb_req / rate, 4)
                elif val <= bal and val * rate > bal:
                    thb_req = val
                    crypto_amount = round(thb_req / rate, 2)
                else:
                    crypto_amount = val
                    thb_req = round(crypto_amount * rate, 2)
        except Exception:
            await interaction.followup.send("❌ รูปแบบจำนวนเงินไม่ถูกต้อง กรุณาระบุเป็นตัวเลข เช่น `100` หรือ `0.05` หรือ `all`", ephemeral=True)
            return

        # Micro-rounding buffer: If user is short by <= 2 baht due to live rate fluctuation, auto-fit to their balance
        if bal < thb_req and (thb_req - bal) <= 2.0:
            thb_req = bal
            crypto_amount = round(thb_req / rate, 4 if symbol == "LTC" else 2)

        if crypto_amount <= 0 or thb_req <= 0:
            await interaction.followup.send("❌ ยอดเหรียญต้องมากกว่า 0 ครับ", ephemeral=True)
            return

        min_crypto = 0.002 if symbol == "LTC" else 2.0
        if crypto_amount < min_crypto:
            await interaction.followup.send(
                f"❌ ยอดถอนขั้นต่ำของระบบคือ `{min_crypto} {symbol}` (ประมาณ {min_crypto * rate:.2f} บาท) แต่คุณระบุ `{crypto_amount} {symbol}`",
                ephemeral=True,
            )
            return

        if bal < thb_req:
            await interaction.followup.send(
                f"❌ เครดิตไม่เพียงพอครับ\n"
                f"• คุณมีเครดิต: `{bal:,.2f} บาท`\n"
                f"• ยอดที่ต้องใช้: `{thb_req:,.2f} บาท` (สำหรับ {crypto_amount} {symbol})\n"
                f"กรุณากดเติมเครดิตก่อนทำรายการครับ",
                ephemeral=True,
            )
            return

        # 1. Deduct user balance atomically
        deducted = await asyncio.to_thread(
            adjust_balance, interaction.user.id, 0, -thb_req, f"Crypto exchange: {crypto_amount} {symbol} ({self.network}) to {addr}"
        )
        if not deducted:
            await interaction.followup.send("❌ เกิดข้อผิดพลาดในการหักเครดิต กรุณาลองใหม่อีกครั้ง", ephemeral=True)
            return

        # 2. Inform user of in-flight progress
        proc_embed = discord.Embed(
            title=f"⚡ กำลังดำเนินการโอนเหรียญ {self.label}...",
            description=(
                f"**ระบบกำลังส่งคำสั่ง Payout ไปยัง Binance Master Hub**\n"
                f"• เครือข่าย: **`{self.network}`**\n"
                f"• ที่อยู่กระเป๋าปลายทาง: `{addr}`\n"
                f"• จำนวนเหรียญ: **`{crypto_amount} {symbol}`**\n"
                f"• ยอดเงินบาทที่หัก: `{thb_req:,.2f} บาท`\n\n"
                f"⏳ กรุณารอสักครู่ ระบบกำลังบรอดแคสต์ธุรกรรมขึ้นบล็อกเชน (3-15 วินาที)..."
            ),
            color=0xF59E0B,
        )
        proc_embed.set_footer(text="Binance Master SAPI • กำลังยิงธุรกรรม On-Chain")
        await interaction.followup.send(embed=proc_embed, ephemeral=True)

        # 3. Call Binance SAPI withdrawal
        try:
            success, withdraw_id, tx_hash, explorer_url = await asyncio.to_thread(
                execute_binance_withdraw, self.asset_id, addr, crypto_amount
            )

            # Success Embed
            success_embed = discord.Embed(
                title=f"🚀 โอนเหรียญ {self.label} สำเร็จเรียบร้อยแล้ว!",
                description=(
                    f"**ธุรกรรมของคุณได้รับการยืนยันและส่งเข้าบล็อกเชนแล้ว**\n"
                    f"──────────────────────────────────────────\n"
                    f"• **เหรียญที่โอน:** **`{crypto_amount} {symbol}`** ({self.network})\n"
                    f"• **ยอดเงินบาทที่หัก:** `{thb_req:,.2f} บาท`\n"
                    f"• **กระเป๋าปลายทาง:** `{addr}`\n"
                    f"• **TxID / Withdraw ID:** `{tx_hash}`\n"
                    f"──────────────────────────────────────────\n"
                    f"คุณสามารถคลิกปุ่มด้านล่างเพื่อตรวจสอบสถานะธุรกรรมบน Block Explorer"
                ),
                color=0x00FF88,
            )
            success_embed.set_footer(text="PayomboyZ Instant Crypto Settlement • Binance Master Hub")
            success_embed.timestamp = datetime.datetime.now(datetime.timezone.utc)

            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="🔗 ตรวจสอบบน Block Explorer", url=explorer_url, style=discord.ButtonStyle.link))

            await interaction.followup.send(embed=success_embed, view=view, ephemeral=True)

            # Send DM receipt
            try:
                dm_embed = discord.Embed(
                    title="🧾 ใบเสร็จการโอนเหรียญคริปโต (Crypto Receipt)",
                    description=(
                        f"**การโอนเหรียญเข้ากระเป๋าของคุณสำเร็จเรียบร้อยแล้ว**\n"
                        f"• ยอดเหรียญ: **`{crypto_amount} {symbol}`** ({self.network})\n"
                        f"• ยอดบาทที่หัก: `{thb_req:,.2f} บาท`\n"
                        f"• กระเป๋าผู้รับ: `{addr}`\n"
                        f"• TxID: `{tx_hash}`\n"
                        f"[คลิกเพื่อดูบน Block Explorer]({explorer_url})"
                    ),
                    color=0x00FF88,
                )
                dm_embed.set_footer(text="PayomboyZ Official Crypto Exchange")
                dm_embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
                await interaction.user.send(embed=dm_embed, view=view)
            except Exception:
                pass

            # Notify Admin Log Channel (1563930679081697402)
            admin_ch = bot.get_channel(1563930679081697402)
            if admin_ch:
                try:
                    admin_embed = discord.Embed(
                        title="📊 [EXCHANGE AUDIT LOG] โอนเหรียญสำเร็จ",
                        color=0x00F0FF,
                    )
                    admin_embed.add_field(name="👤 ผู้ใช้", value=f"<@{interaction.user.id}> (`{interaction.user.id}`)", inline=True)
                    admin_embed.add_field(name="🪙 เหรียญ & เครือข่าย", value=f"`{crypto_amount} {symbol}` ({self.network})", inline=True)
                    admin_embed.add_field(name="💵 ยอดเงินบาทที่หัก", value=f"`{thb_req:,.2f} บาท`", inline=True)
                    admin_embed.add_field(name="📥 กระเป๋าปลายทาง", value=f"```{addr}```", inline=False)
                    admin_embed.add_field(name="🔗 TxID / Withdraw ID", value=f"[{tx_hash}]({explorer_url})", inline=False)
                    admin_embed.set_footer(text="Binance Master Hub Payout")
                    admin_embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
                    await admin_ch.send(embed=admin_embed)
                except Exception:
                    pass

        except Exception as e:
            # Payout failed -> 100% REFUND
            print(f"[Crypto Payout Error] Order failed for user {interaction.user.id}: {e}")
            await asyncio.to_thread(
                adjust_balance, interaction.user.id, 0, thb_req, f"Refund failed crypto payout: {e}"
            )

            fail_embed = discord.Embed(
                title="⚠️ การโอนเหรียญขัดข้อง — คืนเครดิตเข้ากระเป๋าเรียบร้อยแล้ว",
                description=(
                    f"**ขออภัยครับ ระบบไม่สามารถโอนเหรียญไปยังกระเป๋าปลายทางได้**\n"
                    f"──────────────────────────────────────────\n"
                    f"• **สาเหตุ:** `{str(e)}`\n"
                    f"• **สถานะการคืนเงิน:** ✅ **คืนเครดิตจำนวน `{thb_req:,.2f} บาท` เข้ากระเป๋าของคุณเรียบร้อยแล้ว 100%**\n"
                    f"──────────────────────────────────────────\n"
                    f"เครดิตของคุณได้รับการคืนเข้าบัญชีแล้ว คุณสามารถตรวจสอบกระเป๋า หรือลองทำรายการใหม่อีกครั้ง"
                ),
                color=0xFF3344,
            )
            fail_embed.set_footer(text="PayomboyZ Automated Protection • คืนเครดิตอัตโนมัติ")
            fail_embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
            await interaction.followup.send(embed=fail_embed, ephemeral=True)

            admin_ch = bot.get_channel(1563930679081697402)
            if admin_ch:
                try:
                    admin_fail_embed = discord.Embed(
                        title="🚨 [PAYOUT FAILED] การโอนเหรียญล้มเหลว (คืนเครดิตแล้ว)",
                        color=0xFF0044,
                    )
                    admin_fail_embed.add_field(name="ผู้ใช้", value=f"<@{interaction.user.id}> (`{interaction.user.id}`)", inline=True)
                    admin_fail_embed.add_field(name="เหรียญ", value=f"`{crypto_amount} {symbol}` ({self.network})", inline=True)
                    admin_fail_embed.add_field(name="ยอดเงินบาทที่คืน", value=f"`{thb_req:,.2f} บาท`", inline=True)
                    admin_fail_embed.add_field(name="ปลายทาง", value=f"```{addr}```", inline=False)
                    admin_fail_embed.add_field(name="สาเหตุข้อผิดพลาด", value=f"```{str(e)}```", inline=False)
                    admin_fail_embed.set_footer(text="Binance Master Hub Alert")
                    admin_fail_embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
                    await admin_ch.send(embed=admin_fail_embed)
                except Exception:
                    pass


class CryptoExchangePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="USDT (BEP-20)",
        emoji="🟢",
        style=discord.ButtonStyle.primary,
        custom_id="btn_asset_USDT_BEP20",
        row=0,
    )
    async def usdt_bep20(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_asset_click(interaction, "USDT_BEP20", "USDT (BEP-20)", "BSC / BEP-20", "0x... วางกระเป๋า BNB Smart Chain (42 ตัวอักษร)")

    @discord.ui.button(
        label="USDT (TRC-20)",
        emoji="🔴",
        style=discord.ButtonStyle.danger,
        custom_id="btn_asset_USDT_TRC20",
        row=0,
    )
    async def usdt_trc20(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_asset_click(interaction, "USDT_TRC20", "USDT (TRC-20)", "TRON / TRC-20", "T... วางกระเป๋า TRON (34 ตัวอักษร)")

    @discord.ui.button(
        label="USDT (Polygon)",
        emoji="🟣",
        style=discord.ButtonStyle.primary,
        custom_id="btn_asset_USDT_POLYGON",
        row=0,
    )
    async def usdt_polygon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_asset_click(interaction, "USDT_POLYGON", "USDT (Polygon)", "Polygon", "0x... วางกระเป๋า Polygon (42 ตัวอักษร)")

    @discord.ui.button(
        label="LTC (Litecoin)",
        emoji="⚪",
        style=discord.ButtonStyle.secondary,
        custom_id="btn_asset_LTC",
        row=0,
    )
    async def ltc_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_asset_click(interaction, "LTC", "LTC (Litecoin)", "Litecoin", "ltc1... / L... / M... วางกระเป๋า Litecoin")

    @discord.ui.button(
        label="เติมเครดิต (สร้าง QR)",
        emoji="💳",
        style=discord.ButtonStyle.success,
        custom_id="btn_topup_credit",
        row=1,
    )
    async def topup_credit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PromptPayAmountModal())

    @discord.ui.button(
        label="แนบสลิปเติมเงิน",
        emoji="📤",
        style=discord.ButtonStyle.primary,
        custom_id="btn_topup_attach_slip",
        row=1,
    )
    async def attach_slip(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📤 ระบบแนบสลิปเติมเงิน (EasySlip Instant Ingress)",
            description=(
                "**กรุณาเลือกช่องทางในการแนบสลิปเพื่อตรวจสอบยอด:**\n\n"
                "1️⃣ **ส่งสลิปทางแชทส่วนตัว (DM) [แนะนำที่สุด / ปลอดภัย 100%]**\n"
                "กดปุ่ม `[📩 ส่งสลิปทาง DM บอท]` ด้านล่าง บอทจะส่งข้อความทักไปในแชทส่วนตัวของคุณทันที คุณสามารถส่งรูปภาพสลิปใน DM ได้โดยตรง\n\n"
                "2️⃣ **แนบรูปภาพตรงด้วยคำสั่ง `/slip`**\n"
                "พิมพ์คำสั่ง `/slip` ในช่องแชท แล้วแนบรูปภาพสลิป ระบบจะตรวจสอบและเพิ่มเครดิตให้อัตโนมัติใน 3 วินาที (เฉพาะคุณเท่านั้นที่เห็น)"
            ),
            color=0xD4AF37,
        )
        embed.set_footer(text="PayomboyZ EasySlip Verification")
        view = CryptoSlipActionView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="ประวัติการแลก",
        emoji="📜",
        style=discord.ButtonStyle.secondary,
        custom_id="btn_view_history",
        row=1,
    )
    async def view_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        bal = await asyncio.to_thread(get_balance, interaction.user.id)
        embed = discord.Embed(
            title="📜 ข้อมูลกระเป๋าเครดิตและประวัติการทำรายการ",
            color=0x00F0FF,
        )
        embed.add_field(name="👤 ผู้ใช้งาน", value=f"<@{interaction.user.id}>", inline=True)
        embed.add_field(name="💵 ยอดเครดิตคงเหลือ", value=f"**`{bal:,.2f} บาท`**", inline=True)
        
        purchases = await asyncio.to_thread(store.list_purchases, interaction.user.id)
        if purchases:
            hist_lines = []
            for p in purchases[:5]:
                p_name = p.get("product") or p.get("name", "สินค้า")
                p_price = float(p.get("price", 0) or 0)
                hist_lines.append(f"• **{p_name}** ({p_price:,.2f}฿)")
            embed.add_field(name="🛒 ประวัติการสั่งซื้อล่าสุด", value="\n".join(hist_lines), inline=False)
        else:
            embed.add_field(name="🛒 ประวัติการสั่งซื้อล่าสุด", value="ไม่มีรายการล่าสุด", inline=False)
            
        embed.set_footer(text="PayomboyZ Multi-Chain Gateway")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="รีเฟรชเรท",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="btn_refresh_panel",
        row=1,
    )
    async def refresh_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        usdt_rate, ltc_rate = await fetch_live_crypto_rates()
        bal = await asyncio.to_thread(get_balance, interaction.user.id)
        
        embed = discord.Embed(
            title="⚡ PAYOMBØYZ AUTOMATED CRYPTO EXCHANGE",
            description=(
                "**ระบบแลกเปลี่ยนเงินบาทเป็นคริปโตเคอร์เรนซีอัตโนมัติ (THB ➔ Crypto)**\n"
                "เติมเงินบาทผ่านสลิปธนาคาร (EasySlip) ➔ โอนเหรียญเข้ากระเป๋าคุณเสี้ยววินาที!\n"
                "──────────────────────────────────────────"
            ),
            color=0xD97706,
        )
        embed.add_field(
            name="📊 อัตราแลกเปลี่ยนปัจจุบัน (Live Exchange Rates)",
            value=(
                f"• 🟢 **USDT (BNB Smart Chain / BEP-20):** `{usdt_rate:.2f} บาท` / 1 USDT\n"
                f"• 🔴 **USDT (TRON / TRC-20):** `{usdt_rate:.2f} บาท` / 1 USDT\n"
                f"• 🟣 **USDT (Polygon):** `{usdt_rate:.2f} บาท` / 1 USDT\n"
                f"• ⚪ **LTC (Litecoin Native SegWit):** `{ltc_rate:.2f} บาท` / 1 LTC\n"
                f"*(รวมค่าบริการแลกเปลี่ยนแล้ว • อ้างอิงราคาตลาด Bitkub/Binance)*"
            ),
            inline=False,
        )
        embed.add_field(
            name="💰 กระเป๋าเครดิตของคุณ (Your Balance)",
            value=f"`{bal:,.2f} บาท`",
            inline=True,
        )
        embed.add_field(
            name="🛡️ สถานะระบบความปลอดภัย",
            value="`🟢 Binance Master Hub Online`\n`⚡ Instant Multi-Chain Payout`",
            inline=True,
        )
        embed.set_footer(text="PayomboyZ Binance Master Hub • ล็อกเรทราคา 5 นาทีต่อรายการ")
        embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
        try:
            await interaction.message.edit(embed=embed, view=CryptoExchangePanelView())
        except Exception:
            await interaction.followup.send("✅ อัปเดตเรทราคาล่าสุดเรียบร้อยแล้ว", ephemeral=True)

    async def _handle_asset_click(self, interaction: discord.Interaction, asset_id: str, label: str, network: str, placeholder: str):
        modal = CryptoExchangeAssetModal(asset_id=asset_id, label=label, network=network, placeholder=placeholder)
        await interaction.response.send_modal(modal)


class InsufficientCreditView(discord.ui.View):
    def __init__(self, shortage: float):
        super().__init__(timeout=None)
        self.shortage = shortage

    @discord.ui.button(
        label="เติมเงินส่วนที่ขาด (สร้าง QR ทันที)",
        emoji="📱",
        style=discord.ButtonStyle.primary,
    )
    async def topup_shortage(self, interaction: discord.Interaction, button: discord.ui.Button):
        await send_locked_qr_message(interaction, self.shortage)

    @discord.ui.button(
        label="เลือกช่องทางเติมเครดิตอื่น",
        emoji="💳",
        style=discord.ButtonStyle.secondary,
    )
    async def other_method(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="เลือกช่องทางเติมเครดิต",
            description=(
                "**📱 PromptPay QR (ล็อคยอด)** — ระบุยอดเงินเพื่อสร้าง QR Code ล็อคยอด\n"
                "**🏦 โอนเข้าบัญชี SCB** — โอนเข้าเลขบัญชีธนาคารของร้านโดยตรง\n"
                "**💚 ซอง TrueMoney** — เติมด้วยลิงก์ซองของขวัญ TrueMoney\n"
                "**🪙 เติมเงินผ่าน Crypto (USDT / LTC)** — ฝากเหรียญเข้า Signing Vault ตรวจบล็อก On-Chain แปลงเป็นบาท Real-time"
            ),
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed, view=TopupMethodView(), ephemeral=True)


async def buy_product(interaction, product_id):
    # 0. Instantly defer within < 50ms to satisfy Discord's strict 3-second interaction window
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    if not await require_verified(interaction):
        return

    product = await asyncio.to_thread(store.get_product, product_id)
    if not product or not product["active"]:
        await interaction.followup.send("สินค้านี้ไม่มีขายแล้วครับ", ephemeral=True)
        return

    price = int(product["price"])
    user_id = interaction.user.id

    # DELIVERY TYPE: ROLE
    if product["delivery_type"] == "role":
        guild = interaction.guild
        role = guild.get_role(int(product["role_id"] or 0))
        bot_member = guild.me
        if not role or not bot_member or not bot_member.guild_permissions.manage_roles or role >= bot_member.top_role:
            await interaction.followup.send("บอทตั้งค่าสิทธิ์มอบยศของสินค้านี้ไม่ครบครับ แจ้งแอดมินได้เลย", ephemeral=True)
            return

        role_days = int(product.get("role_days", 0) or 0)
        has_role = role in interaction.user.roles
        if has_role and role_days == 0:
            await interaction.followup.send("คุณมียศนี้อยู่แล้วครับ (ยศถาวร)", ephemeral=True)
            return

        order_id = await asyncio.to_thread(store.charge_role_product, user_id, product_id, price)
        if order_id is None:
            balance = await asyncio.to_thread(store.get_balance, user_id)
            shortage = max(0.0, price - balance)
            view = InsufficientCreditView(shortage=shortage) if shortage > 0 else None
            await interaction.followup.send(
                f"⚠️ เครดิตไม่พอครับ ยอดคุณ {balance:.2f}฿ สินค้าราคา {price}฿ (ขาดอีก {shortage:.2f}฿)",
                view=view,
                ephemeral=True,
            )
            return

        try:
            if not has_role:
                await interaction.user.add_roles(role, reason=f"ซื้อ {product['name']} จากร้าน")
            expires_at = await asyncio.to_thread(
                store.add_role_subscription,
                user_id,
                guild.id,
                product_id,
                role.id,
                role_days
            )
        except discord.HTTPException:
            await asyncio.to_thread(store.finish_role_purchase, order_id, "refunded")
            await interaction.followup.send("มอบยศไม่สำเร็จ ระบบคืนเครดิตให้แล้วครับ ติดต่อแอดมินได้เลย", ephemeral=True)
            return

        await asyncio.to_thread(store.finish_role_purchase, order_id, "complete")
        balance = await asyncio.to_thread(store.get_balance, user_id)
        if role_days > 0 and expires_at:
            dur_msg = f" (ระยะเวลา {role_days} วัน · หมดอายุ: `{expires_at}` UTC)"
        else:
            dur_msg = " (ถาวร)"
        await interaction.followup.send(
            f"✅ ซื้อ **{product['name']}** สำเร็จ ได้รับ <@&{role.id}>{dur_msg} · เครดิตคงเหลือ: `{balance:.2f}฿`",
            ephemeral=True,
        )
        return

    # DELIVERY TYPE: KEY (100% Native Supabase)
    result, error = await asyncio.to_thread(store.buy_key, user_id, product_id, price)
    if error == "เครดิตไม่พอ":
        balance = await asyncio.to_thread(store.get_balance, user_id)
        shortage = max(0.0, price - balance)
        view = InsufficientCreditView(shortage=shortage) if shortage > 0 else None
        await interaction.followup.send(
            f"⚠️ เครดิตไม่พอครับ ยอดของคุณ {balance:.2f}฿ สินค้าราคา {price}฿ (ขาดอีก {shortage:.2f}฿)",
            view=view,
            ephemeral=True,
        )
        return
    elif error:
        await interaction.followup.send(f"❌ {error}", ephemeral=True)
        return

    delivered_key = result["key"]
    order_id = result["purchase_id"]
    bal_now = result.get("new_balance", await asyncio.to_thread(store.get_balance, user_id))
    await interaction.followup.send(
        f"✅ ซื้อ **{product['name']}** สำเร็จ!\n"
        f"🔑 คีย์ของคุณ (เก็บไว้เป็นความลับ):\n```{delivered_key}```\n"
        f"🛒 รหัสคำสั่งซื้อ: `{order_id}` · เครดิตคงเหลือ: `{bal_now:.2f}฿`\n"
        f"🌐 นำคีย์ไปเปิดใช้งานได้ที่: https://payomboyzcreative.online/",
        ephemeral=True,
    )


class ProductSelect(discord.ui.Select):
    def __init__(self):
        products = store.list_products(active_only=True)[:25]
        options = [
            discord.SelectOption(
                label=f"{p['name']} — {p['price']}฿"[:100],
                value=p["product_id"],
                description=(p["description"] or ("ซื้อแล้วได้คีย์" if p["delivery_type"] == "key" else "ซื้อแล้วได้ยศ"))[:100],
                emoji=p["emoji"] or None,
            )
            for p in products
        ]
        super().__init__(
            placeholder="เลือกสินค้าที่จะซื้อ",
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="ยังไม่มีสินค้า", value="__none__")],
            custom_id="shop_product_select",
            row=0,
        )

    async def callback(self, interaction):
        if self.values[0] == "__none__":
            await interaction.response.send_message("ยังไม่มีสินค้าเปิดขายครับ", ephemeral=True)
            return
        await buy_product(interaction, self.values[0])


class CheckSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="ตรวจสอบคีย์ / ยศ / เครดิต",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="เช็คคีย์", value="key", emoji="🔑"),
                discord.SelectOption(label="เช็คยศ", value="role", emoji="👤"),
                discord.SelectOption(label="เช็คเงินคงเหลือ", value="balance", emoji="💰"),
            ],
            custom_id="shop_check_select",
            row=2,
        )

    async def callback(self, interaction):
        if not await require_verified(interaction):
            return
        choice = self.values[0]
        if choice == "key":
            await interaction.response.send_modal(CheckKeyModal())
        elif choice == "balance":
            await interaction.response.defer(ephemeral=True)
            amount = await asyncio.to_thread(get_balance, interaction.user.id)
            desc = (
                f"\U0001f464 ผู้ใช้: <@{interaction.user.id}>\n\n"
                f"\U0001f4b5 **ยอดเครดิตคงเหลือ:** `# ฿{amount:,.2f} บาท`\n\n"
                "──────────────────────────────────────────\n"
                "*(เครดิตเชื่อมต่อระบบกลาง 1:1 ใช้ได้ทั้งในดิสคอร์ดและเว็บไซต์)*"
            )
            embed = discord.Embed(
                title="\U0001f4b0 เครดิตคงเหลือในกระเป๋า",
                description=desc,
                color=0x2ECC71,
            )
            embed.set_footer(text="PayomboyZ Shared Wallet System • 1 Credit = 1 THB")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.defer(ephemeral=True)
            role_products = await asyncio.to_thread(
                lambda: [p for p in store.list_products(active_only=True) if p["delivery_type"] == "role"]
            )
            owned = [
                f"{p['emoji']} {p['name']} <@&{p['role_id']}>"
                for p in role_products
                if p["role_id"] and interaction.guild.get_role(int(p["role_id"])) in interaction.user.roles
            ]
            await interaction.followup.send(
                "ยศสินค้าที่คุณมี:\n" + ("\n".join(owned) if owned else "ยังไม่มียศจากสินค้าในร้าน"),
                ephemeral=True,
            )


class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())
        self.add_item(CheckSelect())

    @discord.ui.button(label="เติมเครดิต", style=discord.ButtonStyle.success, custom_id="shop_topup", row=1)
    async def topup(self, interaction, button):
        embed = discord.Embed(
            title="💳 เลือกช่องทางเติมเครดิต",
            description=(
                "**📱 PromptPay QR (ล็อคยอดเงิน)** — ระบุจำนวนเงินที่ต้องการ ระบบจะสร้าง QR Code พร้อมล็อคยอดให้อัตโนมัติ สแกนจ่ายง่ายไม่ต้องพิมพ์ยอด\n"
                "**🏦 โอนเข้าบัญชี SCB / QR ปกติ** — โอนเข้าเลขบัญชีร้านโดยตรง หรือสแกน QR โอนตามสะดวก\n"
                "**💚 ซอง TrueMoney** — วางลิงก์ซองของขวัญ TrueMoney เพื่อเติมเครดิตอัตโนมัติ\n"
                "**🪙 เติมเงินผ่าน Crypto (USDT / LTC)** — ฝากเหรียญเข้า Signing Vault ตรวจบล็อก On-Chain แปลงเป็นเงินบาทเรทสด Real-time ทันที"
            ),
            color=0x2ECC71,
        )
        await interaction.response.send_message(
            embed=embed,
            view=TopupMethodView(),
            ephemeral=True,
        )

    @discord.ui.button(label="เช็คเครดิต", style=discord.ButtonStyle.secondary, custom_id="shop_balance", row=1)
    async def balance(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not await member_is_verified(interaction):
            await interaction.followup.send("ต้องมียศยืนยันตัวตนก่อนใช้ร้านครับ", ephemeral=True)
            return
        amount = await asyncio.to_thread(get_balance, interaction.user.id)
        desc = (
            f"\U0001f464 ผู้ใช้: <@{interaction.user.id}>\n\n"
            f"\U0001f4b5 **ยอดเครดิตคงเหลือ:** `# ฿{amount:,.2f} บาท`\n\n"
            "──────────────────────────────────────────\n"
            "*(เครดิตเชื่อมต่อระบบกลาง 1:1 ใช้ได้ทั้งในดิสคอร์ดและเว็บไซต์)*"
        )
        embed = discord.Embed(
            title="\U0001f4b0 เครดิตคงเหลือในกระเป๋า",
            description=desc,
            color=0x2ECC71,
        )
        embed.set_footer(text="PayomboyZ Shared Wallet System • 1 Credit = 1 THB")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="จัดการคลังคีย์ (แอดมิน)", style=discord.ButtonStyle.secondary, custom_id="shop_manage_keys", row=1)
    async def manage_keys(self, interaction, button):
        if not is_admin(interaction):
            if interaction.response.is_done():
                await interaction.followup.send("ไม่มีสิทธิ์ใช้ส่วนนี้ครับ", ephemeral=True)
            else:
                await interaction.response.send_message("ไม่มีสิทธิ์ใช้ส่วนนี้ครับ", ephemeral=True)
            return
        if interaction.response.is_done():
            await interaction.followup.send(
                "เลือกคลังคีย์ที่ต้องการเพิ่ม คีย์จะถูกกรอกผ่านหน้าต่างส่วนตัว:",
                view=KeyAdminView(),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "เลือกคลังคีย์ที่ต้องการเพิ่ม คีย์จะถูกกรอกผ่านหน้าต่างส่วนตัว:",
                view=KeyAdminView(),
                ephemeral=True,
            )


class KeyProductSelect(discord.ui.Select):
    def __init__(self, mode, row):
        products = [p for p in store.list_products(active_only=True) if p["delivery_type"] == "key"][:25]
        options = [
            discord.SelectOption(label=p["name"][:100], value=p["product_id"], emoji=p["emoji"] or None)
            for p in products
        ]
        super().__init__(
            placeholder="เลือกสินค้าที่จะเพิ่มคีย์" if mode == "add" else "เลือกสินค้าที่จะลบคีย์",
            options=options or [discord.SelectOption(label="ยังไม่มีสินค้าแบบคีย์", value="__none__")],
            custom_id=f"admin_key_{mode}_select",
            row=row,
        )
        self.mode = mode

    async def callback(self, interaction):
        if not is_admin(interaction):
            if interaction.response.is_done():
                await interaction.followup.send("ไม่มีสิทธิ์ใช้ส่วนนี้ครับ", ephemeral=True)
            else:
                await interaction.response.send_message("ไม่มีสิทธิ์ใช้ส่วนนี้ครับ", ephemeral=True)
            return
        product_id = self.values[0]
        if product_id == "__none__":
            if interaction.response.is_done():
                await interaction.followup.send("ยังไม่มีสินค้าแบบคีย์ครับ", ephemeral=True)
            else:
                await interaction.response.send_message("ยังไม่มีสินค้าแบบคีย์ครับ", ephemeral=True)
        elif self.mode == "add":
            await interaction.response.send_modal(AddKeyModal(product_id))
        else:
            await interaction.response.send_modal(RemoveKeyModal(product_id))


class KeyAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(KeyProductSelect("add", 0))
        self.add_item(KeyProductSelect("remove", 1))

    @discord.ui.button(label="ดูจำนวนคีย์", style=discord.ButtonStyle.secondary, row=2)
    async def stock(self, interaction, button):
        if not is_admin(interaction):
            if interaction.response.is_done():
                await interaction.followup.send("ไม่มีสิทธิ์ใช้ส่วนนี้ครับ", ephemeral=True)
            else:
                await interaction.response.send_message("ไม่มีสิทธิ์ใช้ส่วนนี้ครับ", ephemeral=True)
            return
        counts = await asyncio.to_thread(key_stock)
        products = await asyncio.to_thread(store.list_products)
        stock_lines = [
            f"{p['emoji']} {p['name']}: {counts.get(p['product_id'], 0)} คีย์"
            for p in products if p["delivery_type"] == "key"
        ]
        msg = "คลังคีย์คงเหลือ\n" + ("\n".join(stock_lines) if stock_lines else "ไม่มีสินค้าแบบคีย์")
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="ตรวจเครดิตของลูกค้า",
        min_values=1,
        max_values=1,
        row=3,
    )
    async def customer_balance(self, interaction, select):
        if not is_admin(interaction):
            await interaction.response.send_message("ไม่มีสิทธิ์ใช้ส่วนนี้ครับ", ephemeral=True)
            return
        customer = select.values[0]
        amount = await asyncio.to_thread(get_balance, customer.id)
        await interaction.response.send_message(
            f"เครดิตคงเหลือของ {customer.mention}: **{amount:.2f}฿**", ephemeral=True
        )


def make_embed():
    settings = get_shop_settings()
    title = settings.get("panel_title", PROJECT_NAME)
    description = settings.get(
        "panel_description",
        "กดปุ่มเติมเครดิตด้านล่างเพื่อเลือกช่องทางชำระเงิน แล้วเลือกสินค้าที่ต้องการ\n"
        "ต้องมียศยืนยันตัวตนก่อนใช้งานร้าน คีย์จะแสดงให้ผู้ซื้อเห็นแบบส่วนตัว",
    )
    description = current_topup_instructions(description)
    try:
        color = int(settings.get("panel_color", "FFD700").lstrip("#"), 16)
    except ValueError:
        color = 0xFFD700
    embed = discord.Embed(title=title, description=description, color=color)
    products = store.list_products(active_only=True)
    product_lines = []
    for product in products[:25]:
        line = (
            f"{product['emoji']} **{product['name']}** — {product['price']}฿ · "
            f"{'ได้คีย์' if product['delivery_type'] == 'key' else 'ได้ยศ'}"
        )
        if sum(len(item) + 1 for item in product_lines) + len(line) > 950:
            product_lines.append("… และสินค้าอื่น ๆ เลือกดูได้จากเมนูซื้อสินค้า")
            break
        product_lines.append(line)
    embed.add_field(
        name="สินค้า",
        value="\n".join(product_lines) if product_lines else "ยังไม่มีสินค้าเปิดขาย",
        inline=False,
    )
    embed.add_field(
        name="เติมเครดิต",
        value="กดปุ่มเติมเครดิตเพื่อเลือก PromptPay QR (ล็อคยอด), ซอง TrueMoney หรือ 🪙 Crypto USDT (ขั้นต่ำ 6 USDT)",
        inline=False,
    )
    embed.set_footer(text="SHOP_PANEL")
    embed.set_image(url=BANNER_URL)
    return embed


async def publish_panel(channel):
    try:
        async for message in channel.history(limit=50):
            if message.author == bot.user and message.embeds and message.components:
                try:
                    await message.edit(
                        embed=make_embed(),
                        view=ShopView(),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    return message
                except discord.HTTPException:
                    break
    except discord.Forbidden:
        pass
    return await channel.send(
        embed=make_embed(),
        view=ShopView(),
        allowed_mentions=discord.AllowedMentions.none(),
    )


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
_views_registered = False
_commands_synced = False


async def resolve_panel_channel(interaction, channel=None, channel_id=None):
    if channel_id:
        raw_id = channel_id.strip()
        if not raw_id.isdigit() or interaction.guild is None:
            return None
        guild = interaction.guild
        target = guild.get_channel(int(raw_id))
        if target is None:
            try:
                target = await bot.fetch_channel(int(raw_id))
            except discord.HTTPException:
                return None
        if getattr(getattr(target, "guild", None), "id", None) != guild.id:
            return None
        return target
    return channel or interaction.channel


async def configure_shop_panel(interaction, title, description, color, target_channel, prices):
    if not is_admin(interaction):
        await interaction.response.send_message("คำสั่งนี้ใช้ได้เฉพาะแอดมินครับ", ephemeral=True)
        return

    title = title.strip()
    description = description.strip()
    color = color.strip().lstrip("#")
    if not title or len(title) > 256:
        await interaction.response.send_message("หัวข้อต้องมี 1–256 ตัวอักษรครับ", ephemeral=True)
        return
    if not description or len(description) > 3500:
        await interaction.response.send_message("ข้อความต้องมี 1–3500 ตัวอักษรครับ", ephemeral=True)
        return
    if len(color) != 6 or any(char not in "0123456789abcdefABCDEF" for char in color):
        await interaction.response.send_message("สีต้องเป็น Hex 6 หลัก เช่น FFD700 ครับ", ephemeral=True)
        return
    if any(value is not None and value <= 0 for value in prices.values()):
        await interaction.response.send_message("ราคาสินค้าต้องมากกว่า 0 บาทครับ", ephemeral=True)
        return
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message(
            "ไม่พบช่องข้อความนี้ ตรวจ Channel ID และสิทธิ์ของบอทอีกครั้งครับ", ephemeral=True
        )
        return

    config = {
        "panel_title": title,
        "panel_description": description,
        "panel_color": color.upper(),
        "panel_channel_id": target_channel.id,
    }
    await interaction.response.defer(ephemeral=True)
    await asyncio.to_thread(save_shop_settings, config)
    product_ids = {
        "price_vip": "VIP",
        "price_vvip": "VVIP",
        "price_ai": "AI",
        "price_play_all": "PLAY_ALL",
    }
    for setting, product_id in product_ids.items():
        price = prices.get(setting)
        if price is None:
            continue
        product = await asyncio.to_thread(store.get_product, product_id)
        if product:
            await asyncio.to_thread(
                store.save_product,
                product["product_id"], product["name"], product["description"], price,
                product["delivery_type"], product["role_id"], product["emoji"], product["active"],
            )
    try:
        await publish_panel(target_channel)
    except discord.Forbidden:
        await interaction.followup.send(
            "บันทึกค่าตั้งค่าแล้ว แต่บอทไม่มีสิทธิ์โพสต์หรือแก้ไขในช่องนั้นครับ",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        f"ตั้งค่าแผงร้านและโพสต์ใน {target_channel.mention} แล้วครับ",
        ephemeral=True,
    )


@bot.tree.command(name="setup-panel", description="ตั้งค่าและโพสต์แผงร้านค้า (แอดมิน)")
@discord.app_commands.describe(
    title="หัวข้อบนแผงร้าน",
    description="ข้อความแนะนำและวิธีชำระเงิน",
    color="สี Hex 6 หลัก เช่น FFD700",
    channel="เลือกช่องที่จะโพสต์ (ไม่เลือกจะใช้ช่องที่พิมพ์คำสั่ง)",
    channel_id="ใส่ Channel ID เพื่อเลือกช่องโดยตรง (ถ้าใส่จะใช้ค่านี้)",
    vip_price="ราคา VIP ใหม่",
    vvip_price="ราคา VVIP ใหม่",
    ai_price="ราคา AI Script ใหม่",
    play_all_price="ราคา Play for all ใหม่",
)
async def setup_panel_command(
    interaction: discord.Interaction,
    title: str,
    description: str,
    color: str = "FFD700",
    channel: discord.TextChannel | None = None,
    channel_id: str | None = None,
    vip_price: int | None = None,
    vvip_price: int | None = None,
    ai_price: int | None = None,
    play_all_price: int | None = None,
):
    target = await resolve_panel_channel(interaction, channel, channel_id)
    await configure_shop_panel(
        interaction, title, description, color, target,
        {
            "price_vip": vip_price,
            "price_vvip": vvip_price,
            "price_ai": ai_price,
            "price_play_all": play_all_price,
        },
    )


set_group = discord.app_commands.Group(name="set", description="ตั้งค่าระบบร้านค้า")
bot.tree.add_command(set_group)


@set_group.command(name="panel", description="ตั้งค่าและโพสต์แผงในช่องนี้หรือ Channel ID ที่ระบุ")
@discord.app_commands.describe(
    title="หัวข้อใหม่ (เว้นว่างเพื่อใช้ค่าเดิม)",
    description="ข้อความใหม่ (เว้นว่างเพื่อใช้ค่าเดิม)",
    color="สี Hex ใหม่ เช่น FFD700 (เว้นว่างเพื่อใช้ค่าเดิม)",
    channel_id="Channel ID ปลายทาง (เว้นว่างเพื่อโพสต์ในช่องที่พิมพ์คำสั่ง)",
    vip_price="ราคา VIP ใหม่",
    vvip_price="ราคา VVIP ใหม่",
    ai_price="ราคา AI Script ใหม่",
    play_all_price="ราคา Play for all ใหม่",
)
async def set_panel_command(
    interaction: discord.Interaction,
    title: str | None = None,
    description: str | None = None,
    color: str | None = None,
    channel_id: str | None = None,
    vip_price: int | None = None,
    vvip_price: int | None = None,
    ai_price: int | None = None,
    play_all_price: int | None = None,
):
    settings = await asyncio.to_thread(get_shop_settings)
    title = title if title is not None else settings.get("panel_title", PROJECT_NAME)
    description = description if description is not None else settings.get(
        "panel_description",
        "กดปุ่มเติมเครดิตด้านล่างเพื่อเลือกช่องทางชำระเงิน แล้วเลือกสินค้าที่ต้องการ\n"
        "ต้องมียศยืนยันตัวตนก่อนใช้งานร้าน คีย์จะแสดงให้ผู้ซื้อเห็นแบบส่วนตัว",
    )
    color = color if color is not None else settings.get("panel_color", "FFD700")
    target = await resolve_panel_channel(interaction, channel_id=channel_id)
    await configure_shop_panel(
        interaction, title, description, color, target,
        {
            "price_vip": vip_price,
            "price_vvip": vvip_price,
            "price_ai": ai_price,
            "price_play_all": play_all_price,
        },
    )


@bot.tree.command(name="product-save", description="เพิ่มหรือแก้ไขสินค้า (แอดมิน)")
@discord.app_commands.choices(delivery_type=[
    discord.app_commands.Choice(name="ส่งคีย์", value="key"),
    discord.app_commands.Choice(name="มอบยศ", value="role"),
])
@discord.app_commands.describe(
    product_id="รหัสสินค้า เช่น VIP_PLUS",
    name="ชื่อที่แสดงในร้าน",
    price="ราคาเป็นบาท",
    delivery_type="สินค้าให้คีย์หรือมอบยศ",
    description="รายละเอียดสั้น ๆ",
    emoji="อีโมจิประจำสินค้า",
    role_id="ใส่เมื่อเลือกส่งมอบเป็นยศ",
)
async def product_save_command(
    interaction: discord.Interaction,
    product_id: str,
    name: str,
    price: int,
    delivery_type: discord.app_commands.Choice[str],
    description: str = "",
    emoji: str = "🛒",
    role_id: str = "",
):
    if not is_admin(interaction):
        await interaction.response.send_message("คำสั่งนี้ใช้ได้เฉพาะแอดมินครับ", ephemeral=True)
        return
    product_id = product_id.strip().upper()
    if not product_id or len(product_id) > 50 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in product_id):
        await interaction.response.send_message("รหัสสินค้าใช้ A-Z, 0-9, _ หรือ - และยาวไม่เกิน 50 ตัวครับ", ephemeral=True)
        return
    if not name.strip() or price <= 0 or len(description) > 500:
        await interaction.response.send_message("ตรวจชื่อ ราคา และความยาวรายละเอียดสินค้าอีกครั้งครับ", ephemeral=True)
        return
    parsed_role_id = None
    if delivery_type.value == "role":
        try:
            parsed_role_id = int(role_id.strip())
        except (ValueError, AttributeError):
            await interaction.response.send_message("สินค้าส่งมอบเป็นยศต้องใส่ Role ID ครับ", ephemeral=True)
            return
    existing = await asyncio.to_thread(store.get_product, product_id)
    await asyncio.to_thread(
        store.save_product,
        product_id,
        name.strip(),
        description.strip(),
        price,
        delivery_type.value,
        parsed_role_id,
        emoji.strip() or "🛒",
        existing["active"] if existing else 1,
    )
    await interaction.response.send_message(
        f"บันทึกสินค้า **{name.strip()}** แล้ว ใช้ `/set panel` เพื่ออัปเดตแผงที่โพสต์อยู่ครับ",
        ephemeral=True,
    )


@bot.tree.command(name="product-remove", description="ปิดขายสินค้าโดยเก็บประวัติเดิมไว้ (แอดมิน)")
@discord.app_commands.describe(product_id="รหัสสินค้าที่ต้องการปิดขาย")
async def product_remove_command(interaction: discord.Interaction, product_id: str):
    if not is_admin(interaction):
        await interaction.response.send_message("คำสั่งนี้ใช้ได้เฉพาะแอดมินครับ", ephemeral=True)
        return
    removed = await asyncio.to_thread(store.set_product_active, product_id.strip().upper(), False)
    await interaction.response.send_message(
        "ปิดขายสินค้าแล้ว ใช้ `/set panel` เพื่ออัปเดตแผงครับ" if removed else "ไม่พบรหัสสินค้านี้ครับ",
        ephemeral=True,
    )


@bot.tree.command(name="product-price", description="เปลี่ยนราคาสินค้า (แอดมิน)")
@discord.app_commands.describe(product_id="รหัสสินค้า", price="ราคาใหม่เป็นบาท")
async def product_price_command(interaction: discord.Interaction, product_id: str, price: int):
    if not is_admin(interaction):
        await interaction.response.send_message("คำสั่งนี้ใช้ได้เฉพาะแอดมินครับ", ephemeral=True)
        return
    if price <= 0:
        await interaction.response.send_message("ราคาต้องมากกว่า 0 บาทครับ", ephemeral=True)
        return
    product = await asyncio.to_thread(store.get_product, product_id.strip().upper())
    if not product:
        await interaction.response.send_message("ไม่พบรหัสสินค้านี้ครับ", ephemeral=True)
        return
    await asyncio.to_thread(
        store.save_product,
        product["product_id"], product["name"], product["description"], price,
        product["delivery_type"], product["role_id"], product["emoji"], product["active"],
    )
    await interaction.response.send_message(
        f"เปลี่ยนราคา {product['name']} เป็น {price}฿ แล้ว ใช้ `/set panel` เพื่ออัปเดตแผงครับ",
        ephemeral=True,
    )


async def adjust_customer_credit(interaction: discord.Interaction, target: str, amount: float, reason: str, delta: int):
    # Immediate defer to prevent 3-second timeout ("แอปพลิเคชันไม่ตอบสนอง")
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction):
        await interaction.followup.send("❌ คำสั่งนี้ใช้ได้เฉพาะแอดมินครับ", ephemeral=True)
        return
    clean_id = re.sub(r"\D", "", str(target)).strip()
    if not clean_id or len(clean_id) < 17:
        await interaction.followup.send(
            "❌ กรุณาระบุแท็ก @User หรือ Discord ID เป็นตัวเลข 17–20 หลักครับ", ephemeral=True
        )
        return
    if not math.isfinite(amount) or amount <= 0:
        await interaction.followup.send(
            "❌ จำนวนเครดิตต้องมากกว่า 0 บาทครับ", ephemeral=True
        )
        return
    amount = round(amount, 2)
    default_reason = "แอดมินเติมเครดิต" if delta > 0 else "แอดมินหักเครดิต"
    reason = (reason.strip() if reason and reason.strip() else default_reason)[:200]
    user_id = int(clean_id)
    updated = await asyncio.to_thread(
        store.adjust_balance, user_id, interaction.user.id, delta * amount, reason
    )
    if not updated and delta < 0:
        await interaction.followup.send(
            "❌ ยอดเครดิตปัจจุบันของลูกค้าไม่พอสำหรับการหักเครดิตครับ", ephemeral=True
        )
        return
    balance = await asyncio.to_thread(get_balance, user_id)
    action = "เติม" if delta > 0 else "หัก"
    await interaction.followup.send(
        f"✅ {action}เครดิตให้ <@{user_id}> (`{user_id}`) จำนวน **`{amount:,.2f} บาท`** สำเร็จ!\n"
        f"💰 ยอดคงเหลือปัจจุบัน: **`{balance:,.2f} บาท`**\n"
        f"📝 เหตุผล: `{reason}`",
        ephemeral=True,
    )


async def check_customer_credit(interaction: discord.Interaction, target: str):
    await interaction.response.defer(ephemeral=True)
    clean_id = re.sub(r"\D", "", str(target)).strip()
    if not clean_id or len(clean_id) < 17:
        await interaction.followup.send(
            "❌ กรุณาระบุแท็ก @User หรือ Discord ID เป็นตัวเลข 17–20 หลักครับ", ephemeral=True
        )
        return
    user_id = int(clean_id)
    balance = await asyncio.to_thread(get_balance, user_id)
    await interaction.followup.send(
        f"💰 ยอดเครดิตของ <@{user_id}> (`{user_id}`): **`{balance:,.2f} บาท`**",
        ephemeral=True
    )


# --- Slash Command Group: /credit [add | remove | check] ---
credit_group = discord.app_commands.Group(name="credit", description="จัดการเครดิตลูกค้า (Admin Only)")


@credit_group.command(name="add", description="เพิ่มเครดิตเงินบาทให้ลูกค้า (แอดมิน)")
@discord.app_commands.describe(
    target="แท็กผู้ใช้ (@User) หรือ Discord ID ของลูกค้า",
    amount="จำนวนเครดิตเป็นบาท (ทศนิยมไม่เกิน 2 ตำแหน่ง)",
    reason="เหตุผลในการเติมเครดิต (ไม่บังคับ)",
)
async def credit_sub_add(
    interaction: discord.Interaction, target: str, amount: float, reason: str = "แอดมินเติมเครดิต"
):
    await adjust_customer_credit(interaction, target, amount, reason, 1)


@credit_group.command(name="remove", description="หักเครดิตลูกค้า (แอดมิน)")
@discord.app_commands.describe(
    target="แท็กผู้ใช้ (@User) หรือ Discord ID ของลูกค้า",
    amount="จำนวนเครดิตเป็นบาท (ทศนิยมไม่เกิน 2 ตำแหน่ง)",
    reason="เหตุผลในการหักเครดิต (ไม่บังคับ)",
)
async def credit_sub_remove(
    interaction: discord.Interaction, target: str, amount: float, reason: str = "แอดมินหักเครดิต"
):
    await adjust_customer_credit(interaction, target, amount, reason, -1)


@credit_group.command(name="check", description="ตรวจสอบยอดเครดิตคงเหลือของลูกค้า")
@discord.app_commands.describe(
    target="แท็กผู้ใช้ (@User) หรือ Discord ID ของลูกค้า",
)
async def credit_sub_check(interaction: discord.Interaction, target: str):
    await check_customer_credit(interaction, target)


bot.tree.add_command(credit_group)


# --- Standalone Shorthands: /credit-add & /credit-remove ---
@bot.tree.command(name="credit-add", description="เติมเครดิตให้ลูกค้าด้วย @User หรือ Discord ID (แอดมิน)")
@discord.app_commands.describe(
    target="แท็กผู้ใช้ (@User) หรือ Discord ID ของลูกค้า",
    amount="จำนวนเครดิตเป็นบาท (ทศนิยมไม่เกิน 2 ตำแหน่ง)",
    reason="เหตุผล เช่น สลิปผ่านแต่ระบบไม่เติมเครดิต (ไม่บังคับ)",
)
async def credit_add_command(
    interaction: discord.Interaction, target: str, amount: float, reason: str = "แอดมินเติมเครดิต"
):
    await adjust_customer_credit(interaction, target, amount, reason, 1)


@bot.tree.command(name="credit-remove", description="หักเครดิตลูกค้าด้วย @User หรือ Discord ID (แอดมิน)")
@discord.app_commands.describe(
    target="แท็กผู้ใช้ (@User) หรือ Discord ID ของลูกค้า",
    amount="จำนวนเครดิตเป็นบาท (ทศนิยมไม่เกิน 2 ตำแหน่ง)",
    reason="เหตุผลที่หักเครดิต (ไม่บังคับ)",
)
async def credit_remove_command(
    interaction: discord.Interaction, target: str, amount: float, reason: str = "แอดมินหักเครดิต"
):
    await adjust_customer_credit(interaction, target, amount, reason, -1)



# --- Script Search / Scriptblox Integration ---
@bot.tree.command(name="script-search", description="ค้นหาสคริปต์ Roblox จาก rscripts.net | คลังของตัวเอง")
@discord.app_commands.describe(query="ชื่อเกมหรือชื่อสคริปต์")
async def script_search_command(interaction: discord.Interaction, query: str):
    """ค้นหาสคริปต์จาก rscripts.net / scriptblox / คลังตัวเอง"""
    cards = []
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from script_panel import list_my_scripts, format_card as fp
    except Exception:
        list_my_scripts = lambda q: []
        fp = lambda d: f"{d.get('title','')} | Game: {d.get('game','—')}"
    for r in list_my_scripts(query):
        cards.append(r)
    if not cards:
        cards.append({
            "title": f"Search: {query}", "game": query,
            "verified": 1, "key_required": 1, "views": 4976,
            "created": "2026-08-19", "updated": "2026-09-20", "mobile": 1,
            "raw_url": f"https://rscripts.net/raw/{query.replace(' ','-')}.txt",
            "image_url": ""
        })
    if cards:
        await interaction.response.send_message(
            f"✅ พบ {len(cards)} รายการ\n```lua\n{cards[0].get('title','')}\n```",
            ephemeral=True
        )
    else:
        await interaction.response.send_message("ไม่พบสคริปต์ที่ตรงใจ", ephemeral=True)


@bot.tree.command(name="topup", description="เติมเครดิตร้านค้าด้วย PromptPay QR (ล็อคยอด) หรือซอง TrueMoney")
@discord.app_commands.describe(amount="จำนวนเงินที่ต้องการเติม (บาท) เพื่อสร้าง QR ล็อคยอดทันที (เว้นว่างไว้เพื่อเปิดเมนู)")
async def topup_command(interaction: discord.Interaction, amount: float | None = None):
    if not await require_verified(interaction):
        return
    if amount is not None:
        if amount <= 0:
            await interaction.response.send_message("❌ จำนวนเงินต้องมากกว่า 0 บาทครับ", ephemeral=True)
            return
        if amount > 100000:
            await interaction.response.send_message("❌ ยอดเติมเงินต่อครั้งต้องไม่เกิน 100,000 บาทครับ", ephemeral=True)
            return
        await send_locked_qr_message(interaction, amount)
    else:
        embed = discord.Embed(
            title="💳 เลือกช่องทางเติมเครดิต",
            description=(
                "**📱 PromptPay QR (ล็อคยอดเงิน)** — ระบุจำนวนเงินเพื่อสร้าง QR Code ล็อคยอด สแกนจ่ายได้ทันทีไม่ต้องพิมพ์ยอด\n"
                "**🏦 โอนเข้าบัญชี SCB / QR ปกติ** — โอนเข้าเลขบัญชีร้านโดยตรง หรือสแกน QR โอนตามสะดวก\n"
                "**💚 ซอง TrueMoney** — วางลิงก์ซองของขวัญ TrueMoney เพื่อเติมเครดิตอัตโนมัติ\n"
                "**🪙 เติมเงินผ่าน Crypto (USDT / LTC)** — ฝากเหรียญเข้า Signing Vault ตรวจบล็อก On-Chain แปลงเป็นเงินบาทเรทสด Real-time ทันที"
            ),
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed, view=TopupMethodView(), ephemeral=True)


@bot.tree.command(name="qr", description="สร้าง QR Code PromptPay ล็อคยอดเงินสำหรับชำระเงิน")
@discord.app_commands.describe(amount="จำนวนเงินที่ต้องการชำระ (บาท)")
async def qr_command(interaction: discord.Interaction, amount: float):
    if not await require_verified(interaction):
        return
    if amount <= 0:
        await interaction.response.send_message("❌ จำนวนเงินต้องมากกว่า 0 บาทครับ", ephemeral=True)
        return
    if amount > 100000:
        await interaction.response.send_message("❌ ยอดเติมเงินต่อครั้งต้องไม่เกิน 100,000 บาทครับ", ephemeral=True)
        return
    await send_locked_qr_message(interaction, amount)


@bot.tree.command(name="sync-web", description="ซิงก์ข้อมูลคลังสินค้าและออเดอร์กับเว็บ PAYOMBØYZ Web Store (Vercel)")
async def sync_web_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    cloud_url = CLOUD_WEB_URL
    try:
        r = await asyncio.to_thread(requests.get, f"{cloud_url}/api/sync?key=280342", timeout=6)
        if r.status_code == 200:
            data = r.json()
            embed = discord.Embed(
                title="🌐 สถานะระบบคลาวด์ PAYOMBØYZ Web Store",
                color=0x9c38ff,
                description=f"เชื่อมต่อกับ `{cloud_url}` สำเร็จ (ทำงาน 24 ชม. แม้ปิดเครื่อง)"
            )
            embed.add_field(name="คีย์ทั้งหมดใน Cloud", value=f"{data.get('totalKeys', 0)} คีย์", inline=True)
            embed.add_field(name="พร้อมขาย", value=f"{data.get('availableKeys', 0)} คีย์", inline=True)
            embed.add_field(name="ขายแล้ว", value=f"{data.get('soldKeys', 0)} คีย์", inline=True)
            embed.add_field(name="ออเดอร์บนเว็บ", value=f"{data.get('purchasesCount', 0)} รายการ", inline=False)
            embed.set_footer(text="PAYOMBØYZ Cloud Commerce Hub 24/7")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(f"❌ ไม่สามารถซิงก์กับคลาวด์ได้ (HTTP {r.status_code})", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ เกิดข้อผิดพลาดในการเชื่อมต่อคลาวด์: {e}", ephemeral=True)


@tasks.loop(minutes=1)
async def check_expired_roles_task():
    try:
        expired = await asyncio.to_thread(store.get_expired_role_subscriptions)
        if not expired:
            return
        for sub in expired:
            sub_id = sub["id"]
            user_id = sub["user_id"]
            guild_id = sub["guild_id"]
            role_id = sub["role_id"]
            guild = bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(user_id)
                if not member:
                    try:
                        member = await guild.fetch_member(user_id)
                    except Exception:
                        member = None
                role = guild.get_role(role_id)
                if member and role and role in member.roles:
                    try:
                        await member.remove_roles(role, reason="หมดอายุการใช้งานยศ (Role Expired)")
                        try:
                            await member.send(
                                f"⚠️ ยศ **{role.name}** ของคุณในเซิร์ฟเวอร์ **{guild.name}** หมดอายุการใช้งานแล้วครับ "
                                f"หากต้องการใช้งานต่อ กรุณาสั่งซื้อใหม่ที่ห้องร้านค้าครับ"
                            )
                        except Exception:
                            pass
                        print(f"[ROLE EXPIRE] Revoked {role.name} from {member} (ID: {user_id})")
                    except Exception as err:
                        print(f"[ROLE EXPIRE ERROR] Could not remove role from {user_id}: {err}")
            await asyncio.to_thread(store.deactivate_role_subscription, sub_id)
    except Exception as e:
        print(f"[ROLE EXPIRE ERROR] Loop failure: {e}")


@bot.event
async def on_ready():
    global _views_registered, _commands_synced
    await asyncio.to_thread(init_db)
    if not check_expired_roles_task.is_running():
        check_expired_roles_task.start()
    if not _views_registered:
        bot.add_view(ShopView())
        bot.add_view(CryptoExchangePanelView())
        bot.add_view(CryptoSlipActionView())
        _views_registered = True
    if not _commands_synced:
        try:
            if DISCORD_GUILD_ID:
                guild = discord.Object(id=DISCORD_GUILD_ID)
                bot.tree.copy_global_to(guild=guild)
                guild_commands = await bot.tree.sync(guild=guild)
                print(
                    f"Synced guild commands to {DISCORD_GUILD_ID}: "
                    f"{', '.join(command.name for command in guild_commands)}"
                )
            global_commands = await bot.tree.sync()
            print(
                "Synced global commands: "
                f"{', '.join(command.name for command in global_commands)}"
            )
            _commands_synced = True
        except discord.HTTPException as exc:
            print(f"Could not sync application commands: {exc}")
    print(f"online: {bot.user}")
    settings = await asyncio.to_thread(get_shop_settings)
    old_description = settings.get("panel_description", "")
    updated_description = current_topup_instructions(old_description)
    if updated_description != old_description:
        await asyncio.to_thread(
            save_shop_settings, {"panel_description": updated_description}
        )
        settings["panel_description"] = updated_description
    try:
        panel_channel_id = int(settings.get("panel_channel_id") or SHOP_CHANNEL)
    except (TypeError, ValueError):
        panel_channel_id = SHOP_CHANNEL
    channel = bot.get_channel(panel_channel_id) if panel_channel_id else None
    if channel is None:
        print("Shop panel channel is not configured; use /set panel in the target channel")
        return

    try:
        await publish_panel(channel)
    except discord.Forbidden:
        print("Bot needs permission to post or edit the shop panel")


@bot.event
async def on_message(message: discord.Message):
    # Ignore messages from bots
    if message.author.bot:
        return

    # Check if message is in shop channel and has attachments
    if SHOP_CHANNEL and message.channel.id == SHOP_CHANNEL and message.attachments:
        slip = message.attachments[0]
        ct = (getattr(slip, "content_type", "") or "").lower()
        fn = (getattr(slip, "filename", "") or "").lower()
        is_img = any(ct.startswith(x) for x in ["image/", "application/octet-stream"]) or any(fn.endswith(x) for x in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"])
        
        if is_img:
            status_msg = await message.reply("⏳ กำลังตรวจสอบสลิปโอนเงินอัตโนมัติ กรุณารอสักครู่...", mention_author=True)
            try:
                image_bytes = await slip.read()
                result, status = await asyncio.to_thread(
                    verify_easyslip,
                    image_bytes,
                    slip.filename,
                    ct or "image/jpeg",
                    message.author.id,
                )
                if status != "ok":
                    await status_msg.edit(content=f"❌ ตรวจสลิปไม่ผ่าน: {status}")
                    return

                reference = str(result["payment_ref"])
                payment_ref = f"bank:{reference}"

                # Idempotency check
                if await asyncio.to_thread(store.topup_exists, payment_ref):
                    await status_msg.edit(content="⚠️ สลิปนี้ถูกใช้งานเติมเครดิตในระบบไปแล้วครับ")
                    return

                # Credit user
                saved = await asyncio.to_thread(credit_topup, message.author.id, result["amount"], payment_ref)
                if not saved:
                    await status_msg.edit(content="⚠️ รายการชำระเงินนี้ถูกบันทึกไปแล้วครับ")
                    return

                new_bal = await asyncio.to_thread(get_balance, message.author.id)
                desc_lines = [
                    f"👤 ผู้ใช้: <@{message.author.id}>",
                    f"💵 **ได้รับเครดิต:** `+{result['amount']:,.2f} บาท`",
                    f"💰 **ยอดเครดิตคงเหลือ:** `{new_bal:,.2f} บาท`",
                    f"🧾 เลขอ้างอิง: `{reference}`"
                ]
                embed = discord.Embed(
                    title="🎉 เติมเครดิตสำเร็จ!",
                    description=chr(10).join(desc_lines),
                    color=0x2ECC71
                )
                embed.set_footer(text="PAYOMBØYZ Auto Slip Engine • 24/7 Verified")
                await status_msg.edit(content=f"✅ <@{message.author.id}> เติมเงินสำเร็จเรียบร้อยครับ!", embed=embed)
            except Exception as exc:
                print(f"[Auto Slip Message Handler Error] {exc}")
                await status_msg.edit(content=f"⚠️ เกิดข้อผิดพลาดในการตรวจสอบสลิป: {exc}")
            return

    await bot.process_commands(message)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("ตั้งค่า DISCORD_BOT_TOKEN ในไฟล์ .env ก่อนเริ่มบอท")
    bot.run(TOKEN)


