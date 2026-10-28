import hmac
import hashlib
import time
import requests
import asyncio
import os
import math
from typing import Dict, Any, Tuple

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "CJdPNL2J9vNdpDVfvFlOWf97PVk9RaxGFf3S2PezU0OMhtt0KNlvgLzGWrUwGVJp")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "3YTIo4tPGnqGFncubn5OO9TKkjWTVA8vY2nKxmSAKZLo85tRSQDlpikuHNo9tYRk")
BASE_URL = "https://api.binance.com"

# Network mapping for Binance
NETWORK_MAP = {
    "USDT_BEP20": ("USDT", "BSC", "https://bscscan.com/tx/"),
    "USDT_TRC20": ("USDT", "TRX", "https://tronscan.org/#/transaction/"),
    "USDT_POLYGON": ("USDT", "MATIC", "https://polygonscan.com/tx/"),
    "LTC": ("LTC", "LTC", "https://live.blockcypher.com/ltc/tx/"),
}

def sign_query(query: str, secret: str = BINANCE_API_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

def get_account_balances() -> Dict[str, float]:
    """Fetch free balances on Binance Spot wallet."""
    ts = int(time.time() * 1000)
    q = f"timestamp={ts}"
    sig = sign_query(q)
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    
    r = requests.get(f"{BASE_URL}/api/v3/account?{q}&signature={sig}", headers=headers, timeout=10)
    if r.status_code != 200:
        raise Exception(f"Binance Account Error ({r.status_code}): {r.text}")
    
    balances = {}
    for b in r.json().get("balances", []):
        free = float(b.get("free", 0.0))
        if free > 0:
            balances[b["asset"]] = free
    return balances

def auto_swap_to_coin(target_coin: str, needed_amount: float) -> bool:
    """
    Two-way automatic market swap:
    - If target is USDT: auto-market SELL LTC to get USDT.
    - If target is LTC: auto-market BUY LTC using USDT.
    """
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    
    r_price = requests.get(f"{BASE_URL}/api/v3/ticker/price?symbol=LTCUSDT", timeout=5)
    if r_price.status_code != 200:
        print(f"[Binance Swap] Failed to fetch ticker for LTCUSDT: {r_price.text}")
        return False
    price = float(r_price.json().get("price", 0))
    if price <= 0:
        return False

    balances = get_account_balances()
    
    if target_coin == "USDT":
        ltc_bal = balances.get("LTC", 0.0)
        # Minimum notional on Binance spot is 5 USDT; request with buffer
        usdt_to_get = max(5.5, round(needed_amount * 1.05, 2))
        ltc_qty_needed = usdt_to_get / price
        ltc_qty = math.ceil(ltc_qty_needed * 1000.0) / 1000.0
        
        if ltc_bal < ltc_qty:
            print(f"[Binance Swap] Insufficient LTC to sell for {needed_amount} USDT (Has {ltc_bal} LTC, needs {ltc_qty} LTC)")
            return False
            
        print(f"[Binance Swap] Selling {ltc_qty:.3f} LTC to get ~{usdt_to_get:.2f} USDT via Market Order...")
        ts = int(time.time() * 1000)
        order_q = f"symbol=LTCUSDT&side=SELL&type=MARKET&quantity={ltc_qty:.3f}&timestamp={ts}"
        order_sig = sign_query(order_q)
        
        r_order = requests.post(f"{BASE_URL}/api/v3/order?{order_q}&signature={order_sig}", headers=headers, timeout=10)
        if r_order.status_code == 200:
            print(f"[Binance Swap] Successfully sold {ltc_qty} LTC for USDT: {r_order.json().get('executedQty')}")
            time.sleep(1.0)
            return True
        else:
            print(f"[Binance Swap Error] {r_order.status_code}: {r_order.text}")
            return False

    elif target_coin == "LTC":
        usdt_bal = balances.get("USDT", 0.0)
        usdt_needed = max(5.5, round(needed_amount * price * 1.05, 2))
        
        if usdt_bal < usdt_needed:
            print(f"[Binance Swap] Insufficient USDT to buy {needed_amount} LTC (Has {usdt_bal} USDT, needs {usdt_needed} USDT)")
            return False
            
        print(f"[Binance Swap] Buying LTC using {usdt_needed:.2f} USDT via Market Order...")
        ts = int(time.time() * 1000)
        order_q = f"symbol=LTCUSDT&side=BUY&type=MARKET&quoteOrderQty={usdt_needed:.2f}&timestamp={ts}"
        order_sig = sign_query(order_q)
        
        r_order = requests.post(f"{BASE_URL}/api/v3/order?{order_q}&signature={order_sig}", headers=headers, timeout=10)
        if r_order.status_code == 200:
            print(f"[Binance Swap] Successfully bought LTC with USDT: {r_order.json().get('executedQty')}")
            time.sleep(1.0)
            return True
        else:
            print(f"[Binance Swap Error] {r_order.status_code}: {r_order.text}")
            return False

    return False

def execute_binance_withdraw(asset_id: str, address: str, amount: float) -> Tuple[bool, str, str, str]:
    """
    Executes real on-chain withdrawal from Binance Spot Wallet.
    Returns: (success: bool, withdraw_id: str, tx_hash: str, explorer_url: str)
    """
    if asset_id not in NETWORK_MAP:
        raise ValueError(f"Unsupported asset: {asset_id}")
    
    coin, network, explorer_prefix = NETWORK_MAP[asset_id]
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    
    # 1. Pre-flight check balance & auto-swap if needed
    balances = get_account_balances()
    current_bal = balances.get(coin, 0.0)
    
    if current_bal < amount:
        print(f"[Binance Withdraw] Balance of {coin} is {current_bal} < requested {amount}. Attempting auto-swap...")
        swapped = auto_swap_to_coin(coin, amount - current_bal)
        if not swapped:
            raise Exception(f"ยอดคงเหลือ {coin} ใน Binance ไม่พอ (มี {current_bal:.4f} {coin}, ต้องใช้ {amount} {coin}) และไม่สามารถแลกจาก USDT ได้")
        
        # Re-check balance after swap
        balances = get_account_balances()
        current_bal = balances.get(coin, 0.0)
        if current_bal < amount:
            raise Exception(f"ยอดคงเหลือ {coin} หลังแลกยังไม่เพียงพอ ({current_bal:.4f} < {amount})")

    # 2. Submit Withdrawal Request
    ts = int(time.time() * 1000)
    params = f"coin={coin}&network={network}&address={address}&amount={amount}&timestamp={ts}"
    sig = sign_query(params)
    
    r_withdraw = requests.post(
        f"{BASE_URL}/sapi/v1/capital/withdraw/apply?{params}&signature={sig}",
        headers=headers,
        timeout=20
    )
    
    if r_withdraw.status_code != 200:
        err_data = r_withdraw.json() if r_withdraw.headers.get("content-type", "").startswith("application/json") else {}
        err_msg = err_data.get("msg", r_withdraw.text)
        err_code = err_data.get("code", r_withdraw.status_code)
        raise Exception(f"Binance SAPI Error ({err_code}): {err_msg}")
    
    withdraw_res = r_withdraw.json()
    withdraw_id = withdraw_res.get("id", "")
    print(f"[Binance Withdraw Success] Withdraw ID: {withdraw_id} for {amount} {coin} to {address}")
    
    # 3. Poll for TxID on-chain (up to 6 times / 15 sec)
    tx_hash = withdraw_id
    for _ in range(6):
        time.sleep(2.5)
        try:
            poll_ts = int(time.time() * 1000)
            hist_q = f"coin={coin}&timestamp={poll_ts}"
            hist_sig = sign_query(hist_q)
            r_hist = requests.get(f"{BASE_URL}/sapi/v1/capital/withdraw/history?{hist_q}&signature={hist_sig}", headers=headers, timeout=5)
            if r_hist.status_code == 200:
                hist_data = r_hist.json()
                for item in hist_data:
                    if item.get("id") == withdraw_id or item.get("withdrawOrderId") == withdraw_id:
                        if item.get("txId"):
                            tx_hash = item.get("txId")
                            print(f"[Binance On-Chain Confirmed] TxID: {tx_hash}")
                            break
                if tx_hash != withdraw_id:
                    break
        except Exception:
            pass
    
    explorer_url = f"{explorer_prefix}{tx_hash}"
    return True, withdraw_id, tx_hash, explorer_url
