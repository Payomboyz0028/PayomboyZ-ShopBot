import http.server
import os
import sys
import threading
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_SCRIPT = os.path.join(SCRIPT_DIR, "src.py")
SERVICE_NAME = os.getenv("RENDER_SERVICE_NAME", "payomboyz-shop")

class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(f'{"status":"online","service":"payomboyz-shop"}\n'.encode("utf-8"))

    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.getenv("PORT", 10000))
    try:
        server = http.server.ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"🚀 [Health Server] Listening on 0.0.0.0:{port} for payomboyz-shop", flush=True)
        server.serve_forever()
    except Exception as exc:
        print(f"⚠️ Health server error: {exc}", flush=True)

if __name__ == "__main__":
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()

    print(f"🤖 [Bot Starter] Executing {BOT_SCRIPT} in cwd {SCRIPT_DIR}...", flush=True)
    proc = subprocess.Popen([sys.executable, BOT_SCRIPT], cwd=SCRIPT_DIR)
    proc.wait()
