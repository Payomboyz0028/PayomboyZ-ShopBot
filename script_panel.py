"""Roblox Script Search Panel — matches Discord bot card UI."""
import sqlite3, os, sys, time, requests
from pathlib import Path

DB = Path("scripts.sqlite3")

def db():
    con = sqlite3.connect(str(DB), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con

def init_panel_db():
    with db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS my_scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, game TEXT, raw_url TEXT,
                verified INTEGER DEFAULT 0, key_required INTEGER DEFAULT 0,
                views INTEGER DEFAULT 0, mobile INTEGER DEFAULT 0,
                created TEXT, updated TEXT,
                image_url TEXT, script_code TEXT,
                source TEXT DEFAULT 'rscripts'
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_my_title ON my_scripts(title)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_my_game ON my_scripts(game)")
        con.commit()

# --- Fetch from rscripts.net (public raw endpoints) ---
def fetch_rscripts(slug):
    url = f"https://rscripts.net/raw/{slug}.txt"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return {"raw": r.text, "url": url, "source": "rscripts"}
    except Exception as exc:
        return {"raw": None, "url": url, "error": str(exc), "source": "rscripts"}

# --- Fetch from scriptblox (GraphQL endpoint) ---
def fetch_scriptblox(query_str, limit=5):
    # scriptblox public endpoint approximation
    try:
        r = requests.post(
            "https://scriptblox.com/graphql",
            json={"query": f"query {{ scripts(search: \"{query_str}\", limit: {limit}) {{ title game verified keyRequired views createdAt updatedAt mobile imageUrl rawContent }} }}"},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            scripts = data.get("data", {}).get("scripts", [])
            return scripts
    except Exception:
        pass
    return []

# --- My own library ---
def add_my_script(**kw):
    with db() as con:
        con.execute("INSERT INTO my_scripts (title,game,raw_url,verified,key_required,views,mobile,created,updated,image_url,script_code,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (kw.get("title"), kw.get("game"), kw.get("raw_url"), kw.get("verified",0), kw.get("key_required",0), kw.get("views",0), kw.get("mobile",0), kw.get("created"), kw.get("updated"), kw.get("image_url"), kw.get("script_code"), kw.get("source","mine")))
        con.commit()

def list_my_scripts(search=""):
    with db() as con:
        q = "SELECT * FROM my_scripts"
        params = []
        if search:
            q += " WHERE title LIKE ? OR game LIKE ?"
            params = [f"%{search}%", f"%{search}%"]
        q += " ORDER BY updated DESC"
        return [dict(r) for r in con.execute(q, params)]

def get_by_title(title):
    with db() as con:
        for r in con.execute("SELECT * FROM my_scripts WHERE title = ?", (title,)):
            return dict(r)
    return None

# --- Card formatter (matches Discord card in screenshots) ---
def format_card(s):
    lines = [
        f"**{s.get('title', 'Untitled')}**",
        f"Game: **{s.get('game', '—')}** 🔥",
        f"● Verified: {'Yes' if s.get('verified') else 'No'}     □ Key: {'Yes' if s.get('key_required') else 'No'}     👑 Views: {s.get('views', 0)}",
        f"🕒 Created: {s.get('created', '—')}     🔄 Updated: {s.get('updated', '—')}     📱 Mobile: {'Yes' if s.get('mobile') else 'No'}",
        "🟢 Script Copy",
        f"```lua\nloadstring(game:HttpGet(\"{s.get('raw_url', '')}\"))()\n```",
    ]
    if s.get("image_url"):
        lines.append(f"![preview]({s.get('image_url')})")
    else:
        lines.append(f"Page 1/1")
    lines.append("◀ ▶  ⧉ Copy Script")
    return "\n".join(lines)

if __name__ == "__main__":
    init_panel_db()
    print("Panel DB ready at", DB)
    # demo fetch
    res = fetch_rscripts("blue-lock-rivals-script")
    print("rscripts fetch:", res.get("url"), "OK?" , bool(res.get("raw")))
