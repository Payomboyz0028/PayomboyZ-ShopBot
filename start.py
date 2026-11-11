# -*- coding: utf-8 -*-
"""
PBG Rock-Solid Production Service Runner for Render (Python 3.9 - 3.12+ compliant)
- Honest HTTP Health Check (200 only when child subprocess is alive, heartbeat fresh, and Discord READY; otherwise 503)
- Resilient Bot Process Supervisor with Exponential Backoff & Cloudflare 1015/429 Cooldown
- Clean sibling keep-alive mesh excluding retired/suspended services
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_SCRIPT = os.path.join(SCRIPT_DIR, "src.py")
SERVICE_NAME = os.getenv("RENDER_SERVICE_NAME", "payomboyz-shop")
SUPERVISOR_DIR = os.getenv("HUB_SUPERVISOR_DIR") or tempfile.mkdtemp(prefix="payomboyz_shop_")
HEARTBEAT_FILE = os.path.join(SUPERVISOR_DIR, "shop.json")
COOLDOWN_FILE = os.path.join(SUPERVISOR_DIR, "cooldown.json")
RESTART_FILE = os.path.join(SUPERVISOR_DIR, "restart.json")
HEARTBEAT_MAX_AGE = float(os.getenv("HEARTBEAT_MAX_AGE_SECONDS", "45"))
RATELIMIT_EXIT_CODE = 10

_STATE_LOCK = threading.Lock()
_STATE = {
    "proc": None,
    "pid": None,
    "started_at": 0.0,
    "last_exit_code": None,
    "cooldown_until": 0.0,
    "cooldown_reason": None,
}


def _compute_health_snapshot():
    now = time.time()
    with _STATE_LOCK:
        proc = _STATE["proc"]
        pid = _STATE["pid"]
        started_at = _STATE["started_at"]
        last_exit_code = _STATE["last_exit_code"]
        cooldown_until = _STATE["cooldown_until"]
        cooldown_reason = _STATE["cooldown_reason"]

    proc_alive = proc is not None and proc.poll() is None
    cooldown_remaining = max(0, int(cooldown_until - now))
    hb_data = None
    hb_age = None
    hb_fresh = False
    ready = False

    if os.path.exists(HEARTBEAT_FILE):
        try:
            hb_age = round(max(0.0, now - os.path.getmtime(HEARTBEAT_FILE)), 2)
            with open(HEARTBEAT_FILE, "r", encoding="utf-8") as fh:
                hb_data = json.load(fh)
            hb_pid = hb_data.get("pid")
            hb_fresh = (pid is None or hb_pid == pid) and hb_age <= HEARTBEAT_MAX_AGE
            ready = bool(hb_data.get("ready"))
        except Exception:
            hb_fresh = False
            ready = False

    healthy = bool(proc_alive and hb_fresh and ready and cooldown_remaining == 0)
    if cooldown_remaining > 0:
        status = "cooldown"
    elif healthy:
        status = "online"
    elif proc_alive and (now - started_at) < 45 and not hb_data:
        status = "starting"
    elif proc_alive:
        status = "degraded"
    else:
        status = "offline"

    payload = {
        "status": status,
        "service": SERVICE_NAME,
        "timestamp": int(now),
        "bot_active": healthy,
        "proc_alive": proc_alive,
        "ready": ready,
        "pid": pid,
        "heartbeat_age_s": hb_age,
        "last_exit_code": last_exit_code,
        "cooldown_remaining_s": cooldown_remaining,
    }
    if cooldown_reason:
        payload["cooldown_reason"] = cooldown_reason
    return (200 if healthy else 503), payload


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            http_code, snap = _compute_health_snapshot()
            payload = json.dumps(snap).encode("utf-8")

            self.send_response(http_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            print(f"[Health Check Error] {e}", flush=True)

    def do_HEAD(self):
        http_code, _ = _compute_health_snapshot()
        self.send_response(http_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.getenv("PORT", 10000))
    try:
        server = http.server.ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"🚀 [Health Server] Listening on 0.0.0.0:{port} for {SERVICE_NAME}", flush=True)
        server.serve_forever()
    except Exception as exc:
        print(f"⚠️ [Health Server Error] {exc}", flush=True)


def run_bot_supervisor():
    """Supervises the bot subprocess with exponential backoff and rate-limit cooldown."""
    print(f"🤖 [Bot Supervisor] Monitoring {BOT_SCRIPT} in cwd {SCRIPT_DIR} (dir={SUPERVISOR_DIR})...", flush=True)
    backoff_steps = [5, 15, 30, 60, 180, 300]
    fail_streak = 0

    child_env = os.environ.copy()
    child_env["PYTHONUNBUFFERED"] = "1"
    child_env["HUB_SUPERVISOR_DIR"] = SUPERVISOR_DIR

    while True:
        for stale in (HEARTBEAT_FILE, COOLDOWN_FILE, RESTART_FILE):
            if os.path.exists(stale):
                try:
                    os.remove(stale)
                except OSError:
                    pass

        proc_start = time.time()
        code = None
        was_cooperative_restart = False
        try:
            print(f"🤖 [Bot Supervisor] Spawning: {BOT_SCRIPT}", flush=True)
            proc = subprocess.Popen([sys.executable, "-u", BOT_SCRIPT], cwd=SCRIPT_DIR, env=child_env)
            with _STATE_LOCK:
                _STATE["proc"] = proc
                _STATE["pid"] = proc.pid
                _STATE["started_at"] = proc_start
                _STATE["cooldown_until"] = 0.0
                _STATE["cooldown_reason"] = None
            code = proc.wait()
            uptime = time.time() - proc_start
            was_cooperative_restart = os.path.exists(RESTART_FILE) and code == 0

            with _STATE_LOCK:
                _STATE["proc"] = None
                _STATE["last_exit_code"] = code

            cooldown_seconds = 0
            cooldown_reason = None
            if os.path.exists(COOLDOWN_FILE):
                try:
                    with open(COOLDOWN_FILE, "r", encoding="utf-8") as cf:
                        cdata = json.load(cf)
                    cooldown_seconds = int(cdata.get("seconds", 600))
                    cooldown_reason = cdata.get("reason") or "rate-limit"
                except Exception:
                    cooldown_seconds = 600
                    cooldown_reason = "rate-limit"

            if code == RATELIMIT_EXIT_CODE and cooldown_seconds <= 0:
                cooldown_seconds = 600
                cooldown_reason = "discord-http-429-or-1015"

            if cooldown_seconds > 0:
                wait_seconds = max(300, min(cooldown_seconds, 1800))
                fail_streak = min(fail_streak + 1, len(backoff_steps) - 1)
                with _STATE_LOCK:
                    _STATE["cooldown_until"] = time.time() + wait_seconds
                    _STATE["cooldown_reason"] = cooldown_reason
                print(
                    f"🛑 [Bot Supervisor] Rate-limit/CF cooldown triggered ({cooldown_reason}, code={code}). "
                    f"Sleeping {wait_seconds}s before retry...",
                    flush=True,
                )
            elif was_cooperative_restart or uptime >= 120:
                fail_streak = 0
                wait_seconds = 5
                print(
                    f"⚠️ [Bot Supervisor] Subprocess exited (code={code}, uptime={uptime:.1f}s). "
                    f"Restarting in {wait_seconds}s...",
                    flush=True,
                )
            else:
                wait_seconds = backoff_steps[min(fail_streak, len(backoff_steps) - 1)]
                fail_streak += 1
                print(
                    f"⚠️ [Bot Supervisor] Subprocess exited early (code={code}, uptime={uptime:.1f}s, "
                    f"streak={fail_streak}). Backoff restart in {wait_seconds}s...",
                    flush=True,
                )
        except Exception as e:
            with _STATE_LOCK:
                _STATE["proc"] = None
            wait_seconds = backoff_steps[min(fail_streak, len(backoff_steps) - 1)]
            fail_streak += 1
            print(f"❌ [Bot Supervisor Error] {e}. Retrying in {wait_seconds}s...", flush=True)

        time.sleep(wait_seconds)


def run_mesh_pinger():
    """
    PBG Anti-Sleep Cloud Mesh Pinger
    Sends HTTP heartbeats to active sibling Render microservices every 180s (3 min).
    """
    import urllib.request

    sibling_urls = [
        "https://payomboyz-aihub.onrender.com",
        "https://payomboyz-bypass.onrender.com",
        "https://sc-script-bot-0mtw.onrender.com",
        "https://payomboyz-solve-bot-us.onrender.com",
    ]

    time.sleep(20)
    print("⚡ [Mesh Pinger] Cloud keep-alive heartbeat loop active (interval: 180s)", flush=True)

    while True:
        for u in sibling_urls:
            try:
                req = urllib.request.Request(
                    u,
                    headers={"User-Agent": "PAYOMBOYZ-KeepAlive-Mesh/2.0"}
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    pass
            except Exception:
                pass
        time.sleep(180)


if __name__ == "__main__":
    t_health = threading.Thread(target=run_health_server, daemon=True)
    t_health.start()

    t_pinger = threading.Thread(target=run_mesh_pinger, daemon=True)
    t_pinger.start()

    run_bot_supervisor()
