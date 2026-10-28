import http.server
import os
import sys
import threading
import runpy

SERVICE_NAME = os.getenv("RENDER_SERVICE_NAME", "payomboyz-shop")
BOT_SCRIPT = "src.py"

class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        payload = f'{"status":"online","service":"payomboyz-shop"}\n'
        self.wfile.write(payload.encode("utf-8"))

    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.getenv("PORT", 10000))
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🚀 [Health Server] Listening on 0.0.0.0:{port} for payomboyz-shop")
    server.serve_forever()

if __name__ == "__main__":
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()
    
    print(f"🤖 [Bot Starter] Executing {BOT_SCRIPT}...")
    runpy.run_path(BOT_SCRIPT, run_name="__main__")
