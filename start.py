# -*- coding: utf-8 -*-
"""
PBG Rock-Solid Production Service Runner for Render (Python 3.9 - 3.12+ compliant)
- Standards-compliant HTTP 200 JSON Health Check with Content-Length & CORS
- Resilient Bot Process Supervisor with Auto-Restart Loop
- Zero-crash thread isolation: Health Check server never dies even if bot restarts
"""
import http.server
import json
import os
import sys
import threading
import subprocess
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_SCRIPT = os.path.join(SCRIPT_DIR, "src.py")
SERVICE_NAME = os.getenv("RENDER_SERVICE_NAME", "payomboyz-shop")

class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = json.dumps({
                "status": "online",
                "service": SERVICE_NAME,
                "timestamp": int(time.time()),
                "bot_active": True
            }).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            print(f"[Health Check Error] {e}", flush=True)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        # Keep logs clean
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
    """Supervises the bot subprocess, auto-restarting if it unexpectedly terminates."""
    print(f"🤖 [Bot Supervisor] Monitoring {BOT_SCRIPT} in cwd {SCRIPT_DIR}...", flush=True)
    restart_delay = 5
    while True:
        try:
            print(f"🤖 [Bot Supervisor] Spawning: {BOT_SCRIPT}", flush=True)
            proc = subprocess.Popen([sys.executable, BOT_SCRIPT], cwd=SCRIPT_DIR)
            code = proc.wait()
            print(f"⚠️ [Bot Supervisor] Subprocess exited with code {code}. Auto-restarting in {restart_delay}s...", flush=True)
        except Exception as e:
            print(f"❌ [Bot Supervisor Error] {e}. Retrying in {restart_delay}s...", flush=True)
        time.sleep(restart_delay)

if __name__ == "__main__":
    # 1. Start HTTP Health Server in background daemon
    t_health = threading.Thread(target=run_health_server, daemon=True)
    t_health.start()

    # 2. Start Bot Supervisor in main thread
    run_bot_supervisor()
