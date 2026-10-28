"""
PAYOMBØYZ DISCORD SHOP & BILLING ENGINE — 100% PURE SUPABASE ARCHITECTURE
Replaces legacy SQLite (shop.sqlite3 / shop.db) with Supabase Cloud Database.
Shared authoritative wallet and key store across Discord Bot, Web Store, and Roblox Cloud.
"""

import os
import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://tfwtcjiaphvtmamlzaxe.supabase.co").strip().rstrip("/")
SUPABASE_KEY = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()

_supabase: Client = None

def get_sb() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase

def init_db():
    """Verify Supabase connection health."""
    try:
        sb = get_sb()
        sb.table("shop_products").select("product_id").limit(1).execute()
        print("[Supabase Engine] Connected to Supabase Cloud Database successfully.")
    except Exception as e:
        print(f"[Supabase Engine Warning] Init check: {e}")

# =========================================================================
# 1. Product Catalog Engine
# =========================================================================

def list_products(active_only=False):
    """List products from Supabase shop_products."""
    try:
        sb = get_sb()
        query = sb.table("shop_products").select("*")
        if active_only:
            query = query.eq("is_active", True)
        res = query.order("sort_order").execute()
        products = []
        for r in res.data:
            products.append({
                "product_id": r.get("product_id"),
                "name": r.get("name") or r.get("product_id"),
                "description": r.get("description") or "",
                "price": int(r.get("price") or 0),
                "delivery_type": r.get("delivery_type") or "key",
                "role_id": r.get("role_id"),
                "role_days": int(r.get("role_days") or r.get("duration_days") or 0),
                "emoji": r.get("emoji") or "🛒",
                "active": 1 if r.get("is_active") else 0,
                "sort_order": int(r.get("sort_order") or 0),
                "image_url": r.get("image_url") or ""
            })
        return products
    except Exception as e:
        print(f"[Supabase list_products Error] {e}")
        return []

def get_product(product_id):
    """Retrieve single product by ID."""
    try:
        sb = get_sb()
        res = sb.table("shop_products").select("*").eq("product_id", str(product_id).strip()).execute()
        if not res.data:
            return None
        r = res.data[0]
        return {
            "product_id": r.get("product_id"),
            "name": r.get("name") or r.get("product_id"),
            "description": r.get("description") or "",
            "price": int(r.get("price") or 0),
            "delivery_type": r.get("delivery_type") or "key",
            "role_id": r.get("role_id"),
            "role_days": int(r.get("role_days") or r.get("duration_days") or 0),
            "emoji": r.get("emoji") or "🛒",
            "active": 1 if r.get("is_active") else 0,
            "sort_order": int(r.get("sort_order") or 0),
            "image_url": r.get("image_url") or ""
        }
    except Exception as e:
        print(f"[Supabase get_product Error] {e}")
        return None

def save_product(product_id, name, description, price, delivery_type, role_id, emoji, active=1, role_days=0, image_url=""):
    """Upsert product into Supabase shop_products."""
    try:
        sb = get_sb()
        payload = {
            "product_id": str(product_id).strip(),
            "name": str(name).strip(),
            "description": str(description or "").strip(),
            "price": int(price),
            "delivery_type": str(delivery_type).strip(),
            "role_id": int(role_id) if role_id and str(role_id).isdigit() else None,
            "emoji": str(emoji or "🛒").strip(),
            "is_active": bool(active),
            "role_days": int(role_days or 0),
            "image_url": str(image_url or "").strip(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        sb.table("shop_products").upsert(payload, on_conflict="product_id").execute()
    except Exception as e:
        print(f"[Supabase save_product Error] {e}")

def set_product_active(product_id, active):
    """Enable or disable product visibility."""
    try:
        sb = get_sb()
        sb.table("shop_products").update({
            "is_active": bool(active),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("product_id", str(product_id).strip()).execute()
    except Exception as e:
        print(f"[Supabase set_product_active Error] {e}")

def upsert_product_from_cloud(p):
    """Sync product from cloud dictionary."""
    prod_id = str(p.get("product_id") or p.get("id") or "").strip()
    if not prod_id:
        return
    name = str(p.get("name") or prod_id)
    desc = str(p.get("description") or "")
    price = int(p.get("price") or 99)
    delivery = "role" if p.get("delivery_type") == "role" else "key"
    role_id = p.get("role_id")
    img = str(p.get("image_url") or "")
    days = int(p.get("role_days") or p.get("duration_days") or 0)
    emoji = str(p.get("emoji") or "🛒")
    active = 1 if p.get("is_active", True) else 0
    save_product(prod_id, name, desc, price, delivery, role_id, emoji, active, days, img)

# =========================================================================
# 2. Customer Wallet & Balance Engine (Authoritative public.members)
# =========================================================================

def get_balance(user_id):
    """Retrieve customer's THB balance from Supabase public.members."""
    try:
        uid = int(user_id)
        sb = get_sb()
        res = sb.table("members").select("balance").eq("discord_id", uid).execute()
        if res.data and len(res.data) > 0:
            return float(res.data[0].get("balance") or 0.0)
        return 0.0
    except Exception as e:
        print(f"[Supabase get_balance Error] {e}")
        return 0.0

def _sync_user_balance_and_topup(sb, uid, new_bal, new_topup=None):
    """Synchronizes user balance and topup stats across both public.members and public.customers."""
    now_iso = datetime.now(timezone.utc).isoformat()
    # 1. Update members table
    mem_payload = {
        "discord_id": uid,
        "username": f"user_{uid}",
        "balance": new_bal,
        "last_active": now_iso
    }
    if new_topup is not None:
        mem_payload["total_topup"] = new_topup
    sb.table("members").upsert(mem_payload, on_conflict="discord_id").execute()

    # 2. Update customers table (Unified Web & Bot SSOT)
    try:
        cust_payload = {
            "balance": new_bal,
            "balance_thb": new_bal,
            "last_active": now_iso
        }
        if new_topup is not None:
            cust_payload["total_topup"] = new_topup
        upd = sb.table("customers").update(cust_payload).eq("discord_id", uid).execute()
        if not upd.data:
            upd2 = sb.table("customers").update(cust_payload).eq("id", str(uid)).execute()
            if not upd2.data:
                cust_insert = {
                    "id": str(uid),
                    "discord_id": uid,
                    "username": f"user_{uid}",
                    "balance": new_bal,
                    "balance_thb": new_bal,
                    "total_topup": new_topup if new_topup is not None else 0,
                    "rank": "Member",
                    "role": "Member",
                    "created_at": now_iso,
                    "last_active": now_iso
                }
                sb.table("customers").upsert(cust_insert, on_conflict="id").execute()
    except Exception as ce:
        print(f"[Supabase customers sync warning] {ce}")

def set_balance(user_id, amount):
    """Set absolute THB balance for customer."""
    try:
        uid = int(user_id)
        val = max(0.0, float(amount))
        sb = get_sb()
        # Ensure member exists
        sb.table("members").upsert({
            "discord_id": uid,
            "username": f"user_{uid}",
            "balance": val,
            "last_active": datetime.now(timezone.utc).isoformat()
        }, on_conflict="discord_id").execute()
        return val
    except Exception as e:
        print(f"[Supabase set_balance Error] {e}")
        return float(amount)

def adjust_balance(user_id, admin_id, delta, reason):
    """Adjust balance by delta (+/-). Records in balance_adjustments."""
    try:
        uid = int(user_id)
        aid = int(admin_id) if admin_id and str(admin_id).isdigit() else 0
        diff = float(delta)
        sb = get_sb()
        cur_bal = get_balance(uid)
        new_bal = cur_bal + diff
        if new_bal < 0:
            return False
        _sync_user_balance_and_topup(sb, uid, new_bal)
        try:
            sb.table("balance_adjustments").insert({
                "user_id": uid,
                "admin_id": aid,
                "delta": diff,
                "reason": str(reason or "Admin Adjustment"),
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[Supabase adjust_balance Error] {e}")
        return False

def credit_topup(user_id, amount, payment_ref):
    """Process topup atomically: record in topups and increment balance across members & customers."""
    try:
        uid = int(user_id)
        amt = float(amount)
        pref = str(payment_ref).strip()
        sb = get_sb()

        # 1. Check idempotency (prevent double credit)
        existing = sb.table("topups").select("payment_ref").eq("payment_ref", pref).execute()
        if existing.data and len(existing.data) > 0:
            print(f"[Topup] Payment {pref} already credited.")
            return False

        # 2. Insert topup receipt
        sb.table("topups").insert({
            "payment_ref": pref,
            "user_id": uid,
            "amount": amt,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()

        # 3. Increment balance & total_topup
        cur_res = sb.table("members").select("balance, total_topup").eq("discord_id", uid).execute()
        cur_bal = 0.0
        cur_topup = 0.0
        if cur_res.data and len(cur_res.data) > 0:
            cur_bal = float(cur_res.data[0].get("balance") or 0.0)
            cur_topup = float(cur_res.data[0].get("total_topup") or 0.0)

        new_bal = cur_bal + amt
        new_topup = cur_topup + amt

        _sync_user_balance_and_topup(sb, uid, new_bal, new_topup)

        # 4. Audit log
        try:
            sb.table("audit_logs").insert({
                "action": "TOPUP_CREDIT",
                "actor": str(uid),
                "details": {"amount": amt, "payment_ref": pref, "new_balance": new_bal},
                "ip_address": "discord_bot"
            }).execute()
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"[Supabase credit_topup Error] {e}")
        return False

def topup_exists(payment_ref):
    """Check if payment reference has already been claimed."""
    try:
        sb = get_sb()
        res = sb.table("topups").select("payment_ref").eq("payment_ref", str(payment_ref).strip()).execute()
        return bool(res.data and len(res.data) > 0)
    except Exception as e:
        print(f"[Supabase topup_exists Error] {e}")
        return False

# =========================================================================
# 3. Key Issuance & Checkout Engine
# =========================================================================

def _resolve_product_tier(product_id: str, product_name: str = "") -> str:
    combined = f"{product_id} {product_name}".lower()
    if "supervip" in combined or "super_vip" in combined or "super_ip" in combined or "superip" in combined:
        return "SUPERVIP"
    if "auto_quest" in combined or "autoquest" in combined or "เควส" in combined or "atq" in combined:
        return "AUTO_QUEST"
    if "web_log" in combined or "weblog" in combined or "web-log" in combined:
        return "WEB_LOG_VVIP"
    if "ai" in combined or "scripthub" in combined or "script_hub" in combined:
        return "AI_VIP"
    if "vvip" in combined:
        return "VVIP"
    return "VIP"

def buy_key(user_id, product_id, price):
    """
    Atomic unified key purchase:
    1. Checks customer balance from Supabase members.
    2. Finds available key or auto-generates a valid tier key.
    3. Deducts balance from Supabase members.
    4. Registers key with status='active', assigned to user.
    5. Records purchase in public.purchases and public.audit_logs.
    """
    try:
        uid = int(user_id)
        pid = str(product_id).strip()
        cost = float(price)
        sb = get_sb()

        product = get_product(pid)
        if not product or not product["active"]:
            return None, "ไม่พบสินค้าหรือสินค้าปิดขายแล้ว"

        cur_bal = get_balance(uid)
        if cur_bal < cost:
            return None, "เครดิตไม่พอ"

        tier = _resolve_product_tier(pid, product["name"])
        days = int(product.get("role_days") or 0)
        now = datetime.now(timezone.utc)
        expiry = (now + timedelta(days=days)).isoformat() if days > 0 and days < 9000 else None
        hwid_resets = 999 if tier in ("SUPERVIP", "WEB_LOG_VVIP") else (5 if tier == "VVIP" else 3)
        order_id = f"pbg_{int(now.timestamp() * 1000)}_{uuid.uuid4().hex[:5]}"

        # 1. Search for pre-seeded available key matching tier
        key_record = None
        avail_res = sb.table("license_keys").select("id, key_string").eq("role", tier).eq("status", "available").limit(1).execute()
        if avail_res.data and len(avail_res.data) > 0:
            key_record = avail_res.data[0]
            key_string = key_record["key_string"]
            # Assign existing key
            sb.table("license_keys").update({
                "status": "active",
                "discord_id": uid,
                "discord_name": f"user_{uid}",
                "expires_at": expiry,
                "note": f"Shop Purchase: {product['name']} | Order: {order_id}",
                "updated_at": now.isoformat()
            }).eq("id", key_record["id"]).execute()
        else:
            # Auto-generate new cryptographically secure key
            rand_code = "-".join("".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)) for _ in range(4))
            key_string = f"PAYOM-{tier}-{rand_code}"
            sb.table("license_keys").insert({
                "key_string": key_string,
                "role": tier,
                "status": "active",
                "discord_id": uid,
                "discord_name": f"user_{uid}",
                "expires_at": expiry,
                "hwid_resets_left": hwid_resets,
                "note": f"Shop Purchase: {product['name']} | Order: {order_id}",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat()
            }).execute()

        # 2. Deduct balance from Supabase members
        new_bal = cur_bal - cost
        sb.table("members").update({
            "balance": new_bal,
            "last_active": now.isoformat()
        }).eq("discord_id", uid).execute()

        # 3. Record purchase in public.purchases
        sb.table("purchases").insert({
            "id": order_id,
            "user_id": uid,
            "product": pid,
            "price": cost,
            "status": "complete",
            "created_at": now.isoformat()
        }).execute()

        # 4. Record in audit_logs
        try:
            sb.table("audit_logs").insert({
                "action": "KEY_PURCHASE",
                "actor": str(uid),
                "target_key": key_string,
                "details": {"product_id": pid, "product_name": product["name"], "price": cost, "order_id": order_id, "new_balance": new_bal},
                "ip_address": "discord_bot"
            }).execute()
        except Exception:
            pass

        return {
            "key": key_string,
            "purchase_id": order_id,
            "new_balance": new_bal
        }, None

    except Exception as e:
        print(f"[Supabase buy_key Error] {e}")
        return None, f"เกิดข้อผิดพลาดในการสั่งซื้อ: {str(e)}"

# =========================================================================
# 4. Role Product Checkout Engine
# =========================================================================

def charge_role_product(user_id, product_id, price):
    """Charge user for Discord role product before assigning role."""
    try:
        uid = int(user_id)
        pid = str(product_id).strip()
        cost = float(price)
        sb = get_sb()

        product = get_product(pid)
        if not product or not product["active"] or product["delivery_type"] != "role":
            return None

        cur_bal = get_balance(uid)
        if cur_bal < cost:
            return None

        order_id = f"role_{int(datetime.now(timezone.utc).timestamp() * 1000)}_{uuid.uuid4().hex[:4]}"
        new_bal = cur_bal - cost

        # Deduct balance
        sb.table("members").update({
            "balance": new_bal,
            "last_active": datetime.now(timezone.utc).isoformat()
        }).eq("discord_id", uid).execute()

        # Record pending purchase
        sb.table("purchases").insert({
            "id": order_id,
            "user_id": uid,
            "product": pid,
            "price": cost,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()

        return order_id
    except Exception as e:
        print(f"[Supabase charge_role_product Error] {e}")
        return None

def finish_role_purchase(order_id, status):
    """Confirm or refund role purchase."""
    try:
        sb = get_sb()
        res = sb.table("purchases").select("user_id, price, status").eq("id", str(order_id)).execute()
        if not res.data:
            return
        row = res.data[0]
        uid = int(row["user_id"])
        price = float(row["price"] or 0.0)

        if status == "refunded":
            cur_bal = get_balance(uid)
            sb.table("members").update({
                "balance": cur_bal + price,
                "last_active": datetime.now(timezone.utc).isoformat()
            }).eq("discord_id", uid).execute()

        sb.table("purchases").update({
            "status": str(status)
        }).eq("id", str(order_id)).execute()
    except Exception as e:
        print(f"[Supabase finish_role_purchase Error] {e}")

def add_role_subscription(user_id, guild_id, product_id, role_id, days=0):
    """Record temporary Discord role expiration."""
    try:
        uid = int(user_id)
        gid = int(guild_id)
        rid = int(role_id)
        d = int(days or 0)
        now = datetime.now(timezone.utc)
        expiry = (now + timedelta(days=d)).isoformat() if d > 0 else None
        sb = get_sb()
        sb.table("role_subscriptions").insert({
            "user_id": uid,
            "guild_id": gid,
            "product_id": str(product_id),
            "role_id": rid,
            "expires_at": expiry,
            "active": 1,
            "created_at": now.isoformat()
        }).execute()
        return expiry
    except Exception as e:
        print(f"[Supabase add_role_subscription Error] {e}")
        return None

def get_expired_role_subscriptions():
    """Retrieve expired active role subscriptions."""
    try:
        sb = get_sb()
        now_str = datetime.now(timezone.utc).isoformat()
        res = sb.table("role_subscriptions").select("*").eq("active", 1).not_.is_("expires_at", "null").lt("expires_at", now_str).execute()
        return res.data or []
    except Exception as e:
        print(f"[Supabase get_expired_role_subscriptions Error] {e}")
        return []

def deactivate_role_subscription(sub_id):
    """Mark role subscription expired/inactive."""
    try:
        sb = get_sb()
        sb.table("role_subscriptions").update({"active": 0}).eq("id", sub_id).execute()
    except Exception as e:
        print(f"[Supabase deactivate_role_subscription Error] {e}")

def get_user_role_subscriptions(user_id):
    """Get active subscriptions for user."""
    try:
        sb = get_sb()
        res = sb.table("role_subscriptions").select("*").eq("user_id", int(user_id)).eq("active", 1).execute()
        return res.data or []
    except Exception as e:
        print(f"[Supabase get_user_role_subscriptions Error] {e}")
        return []

# =========================================================================
# 5. Keys Management & Admin Helpers
# =========================================================================

def add_key(product_id, secret, status="available", owner_id=None, purchase_id=None):
    """Add new key to Supabase license_keys."""
    try:
        sb = get_sb()
        tier = _resolve_product_tier(product_id)
        uid = int(owner_id) if owner_id and str(owner_id).isdigit() else None
        now = datetime.now(timezone.utc).isoformat()
        sb.table("license_keys").insert({
            "key_string": str(secret).strip(),
            "role": tier,
            "status": str(status),
            "discord_id": uid,
            "note": f"Added via Admin/API | Product: {product_id}",
            "created_at": now,
            "updated_at": now
        }).execute()
        return True
    except Exception as e:
        print(f"[Supabase add_key Error] {e}")
        return False

def generate_keys(product_id, count, length=32):
    """Bulk generate keys in Supabase."""
    tier = _resolve_product_tier(product_id)
    generated = []
    sb = get_sb()
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for _ in range(int(count)):
        rand_code = "-".join("".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)) for _ in range(4))
        k = f"PAYOM-{tier}-{rand_code}"
        rows.append({
            "key_string": k,
            "role": tier,
            "status": "available",
            "note": f"Bulk Generated for {product_id}",
            "created_at": now,
            "updated_at": now
        })
        generated.append(k)
    try:
        sb.table("license_keys").insert(rows).execute()
    except Exception as e:
        print(f"[Supabase generate_keys Error] {e}")
    return generated

def remove_key_by_secret(product_id, secret):
    """Delete key from Supabase license_keys."""
    try:
        sb = get_sb()
        res = sb.table("license_keys").delete().eq("key_string", str(secret).strip()).execute()
        return bool(res.data and len(res.data) > 0)
    except Exception as e:
        print(f"[Supabase remove_key_by_secret Error] {e}")
        return False

def list_keys(product_id=None, available_only=False):
    """List license keys."""
    try:
        sb = get_sb()
        query = sb.table("license_keys").select("*")
        if product_id:
            tier = _resolve_product_tier(product_id)
            query = query.eq("role", tier)
        if available_only:
            query = query.eq("status", "available")
        res = query.order("created_at", desc=True).limit(200).execute()
        return res.data or []
    except Exception as e:
        print(f"[Supabase list_keys Error] {e}")
        return []

def key_counts():
    """Count keys by status."""
    try:
        sb = get_sb()
        total = sb.table("license_keys").select("id", count="exact", head=True).execute().count or 0
        avail = sb.table("license_keys").select("id", count="exact", head=True).eq("status", "available").execute().count or 0
        sold = sb.table("license_keys").select("id", count="exact", head=True).eq("status", "active").execute().count or 0
        return {"total": total, "available": avail, "sold": sold}
    except Exception as e:
        print(f"[Supabase key_counts Error] {e}")
        return {"total": 0, "available": 0, "sold": 0}

def check_key(user_id, secret):
    """Lookup key status for user."""
    try:
        sb = get_sb()
        res = sb.table("license_keys").select("*").eq("key_string", str(secret).strip()).execute()
        if not res.data:
            return None
        r = res.data[0]
        return {
            "key": r.get("key_string"),
            "role": r.get("role"),
            "status": r.get("status"),
            "expires_at": r.get("expires_at"),
            "hwid_resets_left": r.get("hwid_resets_left", 3),
            "owner_id": r.get("discord_id")
        }
    except Exception as e:
        print(f"[Supabase check_key Error] {e}")
        return None

def lookup_key(secret):
    return check_key(None, secret)

def list_purchases(user_id):
    """Retrieve purchase history for user."""
    try:
        sb = get_sb()
        res = sb.table("purchases").select("*").eq("user_id", int(user_id)).order("created_at", desc=True).limit(50).execute()
        return res.data or []
    except Exception as e:
        print(f"[Supabase list_purchases Error] {e}")
        return []

def get_settings():
    """Retrieve settings from shop_settings."""
    try:
        sb = get_sb()
        res = sb.table("shop_settings").select("*").execute()
        settings = {}
        for r in res.data or []:
            settings[r.get("setting_key")] = r.get("setting_value")
        return settings
    except Exception as e:
        print(f"[Supabase get_settings Error] {e}")
        return {}

def save_settings(values):
    """Upsert shop settings."""
    try:
        sb = get_sb()
        rows = [{"setting_key": str(k), "setting_value": str(v), "updated_at": datetime.now(timezone.utc).isoformat()} for k, v in values.items()]
        sb.table("shop_settings").upsert(rows, on_conflict="setting_key").execute()
    except Exception as e:
        print(f"[Supabase save_settings Error] {e}")
