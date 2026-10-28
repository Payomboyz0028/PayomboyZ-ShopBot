"""
PAYOMBØYZ DISCORD BOT — Automated Bot-Hosting.net Deployment Script
Uploads clean bot package (src.py, shop_data.py, whitelist_client.py, requirements.txt, .env)
directly to container deployment via Bot-Hosting REST API v1.
"""
import os
import sys
import zipfile
import requests
import io

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

API_KEY = os.getenv("BOT_HOSTING_API_KEY", "bhk_3b575f5eed716cf1fe8ae9c7efa9428433f30984c5118d1b")
DEPLOYMENT_ID = "95762cbf-8c97-47df-819d-94ac2a061917"
BASE_URL = "https://bot-hosting.net/api/v1"

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

def main():
    print("=" * 60)
    print("[DEPLOY] PAYOMBOYZ BOT -> BOT-HOSTING.NET DEPLOYMENT")
    print("=" * 60)

    # 1. Update startup settings
    print("[1/4] Configuring Python 3.12 Runtime & Entrypoint (src.py)...")
    res = requests.patch(
        f"{BASE_URL}/deployments/{DEPLOYMENT_ID}/startup",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "runtime": "python",
            "runtimeVersion": "3.12",
            "entryFile": "src.py"
        },
        timeout=10
    )
    if res.status_code == 200:
        print("  [OK] Startup configuration updated to Python 3.12 (entryFile: src.py)")
    else:
        print(f"  [WARN] Warning setting startup: {res.status_code} {res.text}")

    # 2. Get Signed Upload URL
    print("[2/4] Requesting signed direct upload URL from node...")
    res = requests.post(
        f"{BASE_URL}/deployments/{DEPLOYMENT_ID}/files/upload-url",
        headers=headers,
        timeout=10
    )
    if res.status_code != 200:
        print(f"  [ERROR] Failed to get upload URL: {res.status_code} {res.text}")
        return False

    upload_data = res.json()
    upload_url = upload_data.get("url")
    print(f"  [OK] Upload URL granted on node: {upload_url[:50]}...")

    # 3. Create deployment ZIP
    print("[3/4] Packaging clean bot files into memory zip (size: < 1MB)...")
    deploy_dir = os.path.dirname(os.path.abspath(__file__))
    zip_buffer = io.BytesIO()

    file_count = 0
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(deploy_dir):
            if "__pycache__" in root or ".git" in root:
                continue
            for f in files:
                if f.endswith((".pyc", ".zip", ".sqlite3", ".sqlite", ".db", ".log")) or f == "deploy_to_bot_hosting.py":
                    continue
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, deploy_dir)
                zf.write(full_path, rel_path)
                file_count += 1

    zip_bytes = zip_buffer.getvalue()
    print(f"  [OK] Packaged {file_count} files into zip ({len(zip_bytes) / 1024:.1f} KB)")

    # 4. Upload zip file to node
    print("[4/4] Uploading bot archive to container volume...")
    files_payload = {
        "files": ("bot_deploy.zip", zip_bytes, "application/zip")
    }
    up_res = requests.post(upload_url, files=files_payload, timeout=30)
    print(f"  Upload response: HTTP {up_res.status_code}")

    # Try decompress endpoint if supported
    try:
        decomp_res = requests.post(
            f"{BASE_URL}/deployments/{DEPLOYMENT_ID}/files/decompress",
            headers={**headers, "Content-Type": "application/json"},
            json={"root": "/", "file": "bot_deploy.zip"},
            timeout=10
        )
        print(f"  Decompress response: HTTP {decomp_res.status_code}")
    except Exception as e:
        print(f"  Decompress note: {e}")

    # 5. Power restart container
    print("[5/5] Restarting container on Bot-Hosting node...")
    try:
        import time
        requests.post(
            f"{BASE_URL}/deployments/{DEPLOYMENT_ID}/power",
            headers={**headers, "Content-Type": "application/json"},
            json={"action": "stop"},
            timeout=10
        )
        time.sleep(3)
        res_power = requests.post(
            f"{BASE_URL}/deployments/{DEPLOYMENT_ID}/power",
            headers={**headers, "Content-Type": "application/json"},
            json={"action": "start"},
            timeout=10
        )
        print(f"  [OK] Power restart response: HTTP {res_power.status_code}")
        print("  ⏳ Waiting 10 seconds for bot to initialize...")
        time.sleep(10)
        logs_res = requests.get(
            f"{BASE_URL}/deployments/{DEPLOYMENT_ID}/logs",
            headers=headers,
            timeout=10
        )
        if logs_res.status_code == 200:
            lines = logs_res.json().get("lines", [])
            print("\n--- LIVE SHOP BOT CONSOLE OUTPUT ---")
            for l in lines[-15:]:
                print("  " + l.rstrip())
            print("------------------------------------\n")
    except Exception as e:
        print(f"  Power action warning: {e}")

    print("\n" + "=" * 60)
    print("[DONE] SHOP BOT DEPLOYED AND RESTARTED!")
    print(f"Deployment ID: {DEPLOYMENT_ID}")
    print("Project: aslamdunk7's Workspace")
    print("Dashboard: https://bot-hosting.net/")
    print("=" * 60)
    return True

if __name__ == "__main__":
    main()
