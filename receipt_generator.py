# -*- coding: utf-8 -*-
"""
PayomboyZ Executive Crypto Receipt Generator (Python Pillow Engine)
Matches 1:1 with TypeScript ReceiptService (@napi-rs/canvas)
Produces luxury black/crimson ruby receipt with gold accents, QR code, and logo.
"""
import io
import os
import datetime
from PIL import Image, ImageDraw, ImageFont
import qrcode

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT_REGULAR_PATH = os.path.join(ASSETS_DIR, "font_regular.ttf")
FONT_BOLD_PATH = os.path.join(ASSETS_DIR, "font_bold.ttf")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")

def get_font(size: int, bold: bool = False):
    """Load bundled font, fallback to system fonts, then default."""
    target_path = FONT_BOLD_PATH if bold else FONT_REGULAR_PATH
    if os.path.exists(target_path):
        try:
            return ImageFont.truetype(target_path, size)
        except Exception:
            pass

    # Windows fallback
    win_paths = [
        "C:/Windows/Fonts/LeelaUIb.ttf" if bold else "C:/Windows/Fonts/LeelawUI.ttf",
        "C:/Windows/Fonts/tahomabd.ttf" if bold else "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for p in win_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue

    return ImageFont.load_default()

def get_mono_font(size: int):
    """Monospace font for addresses and TxIDs."""
    mono_paths = [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for p in mono_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return get_font(size, bold=False)

def generate_crypto_receipt(data: dict) -> bytes:
    """
    Generate luxury official crypto receipt image (PNG bytes).
    Expected keys:
      - order_id: str
      - symbol: str (e.g. 'LTC', 'USDT')
      - crypto_amount: str / float
      - network: str (e.g. 'LITECOIN (LTC)', 'BNB Smart Chain (BEP20)')
      - thb_amount: float
      - effective_rate: float
      - network_fee_thb: float
      - recipient_address: str
      - tx_hash: str
      - explorer_url: str
      - date_str: Optional[str]
    """
    width = 760
    height = 1040
    img = Image.new("RGBA", (width, height), (10, 3, 5, 255))
    draw = ImageDraw.Draw(img)

    # 1. Background Gradient (Dark Black to Crimson Ruby)
    for y in range(height):
        ratio = y / height
        if ratio < 0.35:
            r = int(10 + (20 - 10) * (ratio / 0.35))
            g = int(3 + (5 - 3) * (ratio / 0.35))
            b = int(5 + (9 - 5) * (ratio / 0.35))
        elif ratio < 0.7:
            sub = (ratio - 0.35) / 0.35
            r = int(20 + (24 - 20) * sub)
            g = int(5 + (7 - 5) * sub)
            b = int(9 + (13 - 9) * sub)
        else:
            sub = (ratio - 0.7) / 0.3
            r = int(24 + (6 - 24) * sub)
            g = int(7 + (2 - 7) * sub)
            b = int(13 + (3 - 13) * sub)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # Radial Glow at upper section
    glow_center_x, glow_center_y = width // 2, 170
    max_radius = 360
    glow_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_overlay)
    for r in range(max_radius, 20, -8):
        alpha = int(45 * (1.0 - (r / max_radius))**1.5)
        if alpha > 0:
            glow_draw.ellipse(
                [glow_center_x - r, glow_center_y - r, glow_center_x + r, glow_center_y + r],
                fill=(220, 38, 38, alpha)
            )
    img = Image.alpha_composite(img, glow_overlay)
    draw = ImageDraw.Draw(img)

    # Outer Burnished Gold Border
    gold = (212, 175, 55, 255)
    gold_bright = (255, 215, 0, 255)
    draw.rectangle([20, 20, width - 20, height - 20], outline=gold, width=2)
    # Inner subtle border
    draw.rectangle([26, 26, width - 26, height - 26], outline=(217, 119, 6, 75), width=1)

    # Gold corner brackets
    corner_len = 36
    draw.line([(20, 20 + corner_len), (20, 20), (20 + corner_len, 20)], fill=gold_bright, width=3)
    draw.line([(width - 20 - corner_len, 20), (width - 20, 20), (width - 20, 20 + corner_len)], fill=gold_bright, width=3)
    draw.line([(20, height - 20 - corner_len), (20, height - 20), (20 + corner_len, height - 20)], fill=gold_bright, width=3)
    draw.line([(width - 20 - corner_len, height - 20), (width - 20, height - 20), (width - 20, height - 20 - corner_len)], fill=gold_bright, width=3)

    # 2. Header & Logo
    logo_x = 45
    logo_y = 40
    logo_size = 50
    has_logo = False

    if os.path.exists(LOGO_PATH):
        try:
            logo_img = Image.open(LOGO_PATH).convert("RGBA").resize((logo_size, logo_size), Image.Resampling.LANCZOS)
            # Create rounded mask for logo
            mask = Image.new("L", (logo_size, logo_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([0, 0, logo_size, logo_size], radius=10, fill=255)
            img.paste(logo_img, (logo_x, logo_y), mask)
            # Gold outline around logo
            draw.rounded_rectangle([logo_x, logo_y, logo_x + logo_size, logo_y + logo_size], radius=10, outline=gold, width=2)
            has_logo = True
        except Exception:
            pass

    title_x = (logo_x + logo_size + 14) if has_logo else 45
    draw.text((title_x, 44), "PAYOMBØYZ CRYPTO VAULT", fill=gold_bright, font=get_font(22, bold=True))
    draw.text((title_x, 76), "OFFICIAL EXECUTIVE TRANSACTION RECEIPT (ใบเสร็จรับเงินอย่างเป็นทางการ)", fill=(156, 163, 175, 255), font=get_font(12))

    # Badge: BINANCE VAULT VERIFIED
    badge_x = width - 245
    badge_y = 46
    draw.rounded_rectangle([badge_x, badge_y, badge_x + 200, badge_y + 34], radius=17, fill=(185, 28, 28, 70), outline=(217, 119, 6, 255), width=1)
    # Checkmark
    draw.line([(badge_x + 18, badge_y + 17), (badge_x + 23, badge_y + 22), (badge_x + 32, badge_y + 12)], fill=(253, 224, 71, 255), width=2)
    draw.text((badge_x + 40, badge_y + 8), "BINANCE VAULT VERIFIED", fill=(253, 224, 71, 255), font=get_font(12, bold=True))

    # Divider Line
    draw.line([(45, 106), (width - 45, 106)], fill=(245, 158, 11, 150), width=1)

    # 3. Hero Section (Delivered Crypto)
    draw.text((45, 126), "TOTAL CRYPTO TRANSFERRED (ยอดเหรียญสุทธิที่ได้รับ)", fill=(252, 165, 165, 255), font=get_font(12))
    coin_symbol = str(data.get("symbol", "LTC")).upper()
    amount_str = f"+ {data.get('crypto_amount', '0.00')} {coin_symbol}"
    draw.text((45, 146), amount_str, fill=(255, 255, 255, 255), font=get_font(40, bold=True))

    # Network Pill
    net_pill = f"NETWORK: {data.get('network', 'LITECOIN (LTC)')} • BINANCE SAPI"
    pill_font = get_font(11, bold=True)
    bbox = draw.textbbox((0, 0), net_pill, font=pill_font)
    pill_w = (bbox[2] - bbox[0]) + 24
    draw.rounded_rectangle([45, 204, 45 + pill_w, 204 + 26], radius=6, fill=(153, 27, 27, 100), outline=(217, 119, 6, 255), width=1)
    draw.text((57, 210), net_pill, fill=(252, 211, 77, 255), font=pill_font)

    # Divider
    draw.line([(45, 246), (width - 45, 246)], fill=(245, 158, 11, 150), width=1)

    # 4. Two-Column Metadata Grid
    col1_x = 45
    col2_x = width // 2 + 10
    grid_y = 268
    line_spacing = 50

    def draw_row(l_lbl, l_val, l_col, r_lbl, r_val, r_col, y):
        draw.text((col1_x, y), l_lbl, fill=(156, 163, 175, 255), font=get_font(12))
        draw.text((col2_x, y), r_lbl, fill=(156, 163, 175, 255), font=get_font(12))
        draw.text((col1_x, y + 18), l_val, fill=l_col, font=get_font(13, bold=True))
        draw.text((col2_x, y + 18), r_val, fill=r_col, font=get_font(13, bold=True))

    order_id = str(data.get("order_id", "N/A"))
    date_str = data.get("date_str", datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    draw_row("ORDER REFERENCE (รหัสออเดอร์)", f"#{order_id[:12].upper()}", (226, 232, 240, 255),
             "DATE & TIME (วัน-เวลาทำรายการ)", date_str, (226, 232, 240, 255), grid_y)

    grid_y += line_spacing
    thb_debit = float(data.get("thb_amount", 0.0))
    rate = float(data.get("effective_rate", 0.0))
    draw_row("THB AMOUNT DEBITED (ยอดเงินที่หัก)", f"{thb_debit:,.2f} บาท (THB)", (248, 113, 113, 255),
             "EFFECTIVE RATE (อัตราแลกเปลี่ยนสุทธิ)", f"{rate:,.2f} THB / 1 {coin_symbol}", (253, 224, 71, 255), grid_y)

    grid_y += line_spacing
    fee = float(data.get("network_fee_thb", 5.0))
    net_thb = max(0.0, thb_debit - fee)
    draw_row("NETWORK GAS FEE (ค่าธรรมเนียมบล็อกเชน)", f"{fee:,.2f} บาท", (252, 165, 165, 255),
             "NET EXCHANGE VALUE (ยอดแปลงเหรียญสุทธิ)", f"{net_thb:,.2f} บาท", (251, 191, 36, 255), grid_y)

    grid_y += line_spacing
    draw.line([(45, grid_y), (width - 45, grid_y)], fill=(245, 158, 11, 150), width=1)
    grid_y += 18

    # 5. Destination Wallet Address Box
    draw.text((45, grid_y), "RECIPIENT WALLET ADDRESS (กระเป๋าปลายทางผู้รับ)", fill=(252, 165, 165, 255), font=get_font(12))
    grid_y += 20
    draw.rounded_rectangle([45, grid_y, width - 45, grid_y + 48], radius=8, fill=(16, 4, 7, 255), outline=(127, 29, 29, 255), width=1)
    addr = str(data.get("recipient_address", "N/A"))
    draw.text((60, grid_y + 14), addr, fill=(252, 165, 165, 255), font=get_mono_font(13))
    grid_y += 66

    # 6. Transaction Hash (TxID) Box
    draw.text((45, grid_y), "TRANSACTION HASH (รหัสอ้างอิงบล็อกเชน TxID)", fill=(253, 224, 71, 255), font=get_font(12))
    grid_y += 20
    draw.rounded_rectangle([45, grid_y, width - 45, grid_y + 48], radius=8, fill=(16, 4, 7, 255), outline=(217, 119, 6, 255), width=1)
    tx_hash = str(data.get("tx_hash", "N/A"))
    draw.text((60, grid_y + 14), tx_hash, fill=gold_bright, font=get_mono_font(13))
    grid_y += 66

    # 7. QR Code Box
    qr_box_y = grid_y
    qr_box_h = 148
    draw.rounded_rectangle([45, qr_box_y, width - 45, qr_box_y + qr_box_h], radius=10, fill=(24, 7, 12, 230), outline=gold, width=1)

    # Generate QR Code
    explorer_url = str(data.get("explorer_url", f"https://blockchair.com/litecoin/transaction/{tx_hash}"))
    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=4, border=1)
        qr.add_data(explorer_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#ffd700", back_color="#0a0305").convert("RGBA")
        qr_img = qr_img.resize((124, 124))
        img.paste(qr_img, (width - 182, qr_box_y + 12))
    except Exception:
        pass

    # Text inside QR Box
    draw.text((65, qr_box_y + 24), "สแกน QR Code เพื่อตรวจสอบสถานะสดบนบล็อกเชน", fill=(255, 255, 255, 255), font=get_font(15, bold=True))
    draw.text((65, qr_box_y + 54), "ใช้กล้องสมาร์ทโฟนสแกน QR Code ด้านขวาเพื่อเปิดดูบันทึกธุรกรรมแบบ Raw Tx", fill=(203, 213, 225, 255), font=get_font(12))
    draw.text((65, qr_box_y + 74), "บน Public Block Explorer (BscScan / TronScan / PolygonScan) ได้ทันที", fill=(203, 213, 225, 255), font=get_font(12))
    draw.text((65, qr_box_y + 108), "IMMUTABLE • BINANCE MASTER SAPI • INSTANT CONFIRMED", fill=(245, 158, 11, 255), font=get_font(11, bold=True))

    # 8. Footer
    draw.text((width // 2, height - 34), "PAYOMBØYZ EXECUTIVE AUTOMATED ENGINE • SECURED BY BINANCE MASTER LIQUIDITY", fill=(180, 83, 9, 255), font=get_font(11), anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
