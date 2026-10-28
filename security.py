import re
import os
import sys
import logging
from pathlib import Path
from typing import Tuple, List, Optional

# =========================================================================
# 🛡️ PAYOMBØYZ ADVANCED MULTI-LAYER SECURITY & DATA SHIELD (v4.0)
# =========================================================================

# 1. Regex Patterns for Token & Secret Redaction
TOKEN_PATTERNS = [
    # Discord Bot Tokens
    (re.compile(r'([A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,})'), "[REDACTED_DISCORD_TOKEN]"),
    # Discord User Tokens (MFA or standard)
    (re.compile(r'\bmfa\.[A-Za-z0-9_-]{20,}\b'), "[REDACTED_USER_MFA_TOKEN]"),
    (re.compile(r'\b[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{38}\b'), "[REDACTED_USER_TOKEN]"),
    # Bot-Hosting.net API Keys (bhk_...)
    (re.compile(r'\bbhk_[a-f0-9]{40,64}\b', re.IGNORECASE), "[REDACTED_BOT_HOSTING_KEY]"),
    # DeepSeek Official API Keys (sk-[32 hex])
    (re.compile(r'\bsk-[a-f0-9]{32}\b', re.IGNORECASE), "[REDACTED_DEEPSEEK_KEY]"),
    # OpenRouter API Keys (sk-or-v1-[64 hex])
    (re.compile(r'\bsk-or-v1-[a-f0-9]{64}\b', re.IGNORECASE), "[REDACTED_OPENROUTER_KEY]"),
    # Gemini API Keys (AQ.[40+ chars] or AIzaSy[33 chars])
    (re.compile(r'\bAQ\.[A-Za-z0-9_-]{40,}\b'), "[REDACTED_GEMINI_KEY]"),
    (re.compile(r'\bAIzaSy[A-Za-z0-9_-]{33}\b'), "[REDACTED_GOOGLE_KEY]"),
    # ScriptCenter API Keys (scb_...)
    (re.compile(r'\bscb_[a-f0-9]{40,64}\b', re.IGNORECASE), "[REDACTED_SCRIPTCENTER_KEY]"),
    # Vercel / Whitelist API Key
    (re.compile(r'\bd23c5d8d0eeaeb08b49048c566f42daee80a924f50e882c2\b', re.IGNORECASE), "[REDACTED_WHITELIST_KEY]"),
    # Supabase Service Role JWTs (eyJhbGciOi...)
    (re.compile(r'\beyJhbGciOi[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'), "[REDACTED_JWT_TOKEN]"),
    # Discord Webhooks
    (re.compile(r'https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+'), "https://discord.com/api/webhooks/[REDACTED_WEBHOOK]"),
    # Generic API Keys / Passwords in JSON / Query / Env strings
    (re.compile(r'(?i)(["\']?(?:token|secret|password|api_key|apikey)["\']?\s*[:=]\s*["\'])([^"\'\s]{8,})(["\'])'), r'\1[PROTECTED_SECRET]\3')
]

# 2. Path & Host Obfuscation Patterns
PATH_PATTERNS = [
    # Windows User Paths (e.g. C:\Users\PayomboyZ\...)
    (re.compile(r'[A-Za-z]:\\[Uu]sers\\[^\\]+\\'), r'[SERVER_ROOT]\\'),
    (re.compile(r'[A-Za-z]:/[Uu]sers/[^/]+/'), r'[SERVER_ROOT]/'),
    # Linux Container Paths (e.g. /home/container/...)
    (re.compile(r'/home/container/[^\s]+'), r'[CONTAINER_ROOT]'),
    (re.compile(r'/root/[^\s]+'), r'[CONTAINER_ROOT]'),
    # Sensitive file names
    (re.compile(r'\.env(?:\.local|\.dev|\.prod|\.example)?'), r'[CONFIG_FILE]'),
]

# 3. Dangerous Lua Injection Patterns (Host Escape / Remote Code Execution)
DANGEROUS_LUA_PATTERNS = [
    (r'\bos\s*\.\s*execute\b', "คำสั่งสั่งรันโปรแกรมระบบปฏิบัติการ (os.execute)"),
    (r'\bio\s*\.\s*popen\b', "คำสั่งเปิดไปป์คำสั่งระบบ (io.popen)"),
    (r'\bpackage\s*\.\s*loadlib\b', "คำสั่งโหลดไฟล์ DLL/Binary แปลกปลอม (package.loadlib)"),
    (r'\bdofile\b', "คำสั่งโหลดและรันไฟล์ตรง (dofile)"),
    (r'\bloadfile\b', "คำสั่งโหลดไฟล์จากดิสก์ (loadfile)"),
    (r'\bpowershell(?:\.exe)?\b', "การเรียกใช้งาน PowerShell"),
    (r'\bcmd(?:\.exe)?\b', "การเรียกใช้งาน Windows Command Shell"),
    (r'\bcurl(?:\.exe)?\b', "การสั่งดาวน์โหลดไฟล์ผ่าน curl"),
    (r'\bwget(?:\.exe)?\b', "การสั่งดาวน์โหลดไฟล์ผ่าน wget"),
    (r'\bcertutil(?:\.exe)?\b', "การสั่งดาวน์โหลดหรือเข้ารหัสผ่าน certutil"),
    (r'\bbitsadmin(?:\.exe)?\b', "การสั่งดาวน์โหลดผ่าน bitsadmin"),
    (r'\bmshta(?:\.exe)?\b', "การเรียกใช้งาน Microsoft HTML Application Host"),
    (r'\brundll32(?:\.exe)?\b', "การสั่งรัน DLL ผ่าน rundll32"),
    (r'\.env\b', "ความพยายามเข้าถึงไฟล์ความลับระบบ (.env)"),
    (r'\\Windows\\System32', "ความพยายามเข้าถึงไฟล์ระบบ Windows System32"),
    (r'AppData\\Roaming\\discord', "ความพยายามขโมยข้อมูล Token ของ Discord"),
]


def sanitize_output_text(text: str, secret_token: str = "") -> str:
    """
    Multi-layer Sanitizer: Redacts all tokens, API keys, passwords, webhook URLs,
    and server paths before any output is sent to Discord or logged.
    """
    if not text:
        return text

    sanitized = str(text)

    # 1. Custom specified secret token (exact match)
    if secret_token and len(secret_token) > 8:
        sanitized = sanitized.replace(secret_token, "[REDACTED_PRIMARY_SECRET]")

    # 2. Known environment variables
    for key in ("DISCORD_BOT_TOKEN", "DISCORD_ROLE_BOT_TOKEN", "DISCORD_AI_BOT_TOKEN",
                "CLIENT_SECRET", "DISCORD_ROLE_BOT_CLIENT_SECRET", "BOT_HOSTING_API_KEY",
                "SC_API_KEY", "WHITELIST_API_KEY", "SUPABASE_SERVICE_ROLE_KEY", "EASYSLIP_API_KEY"):
        val = os.getenv(key)
        if val and len(val) > 8:
            sanitized = sanitized.replace(val, f"[REDACTED_{key}]")

    # 3. Regex token redactions
    for pattern, replacement in TOKEN_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    # 4. Path redactions
    for pattern, replacement in PATH_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    return sanitized


class SafeStreamWrapper:
    """Wraps stdout/stderr to automatically redact sensitive tokens in console logs."""
    def __init__(self, original_stream):
        self._orig = original_stream

    def write(self, s):
        if not s:
            return
        cleaned = sanitize_output_text(s)
        try:
            return self._orig.write(cleaned)
        except Exception:
            pass

    def flush(self):
        try:
            return self._orig.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._orig, name)


_INSTALLED_REDACTOR = False

def install_global_redactor():
    """Installs global stdout/stderr redaction filters."""
    global _INSTALLED_REDACTOR
    if _INSTALLED_REDACTOR:
        return
    _INSTALLED_REDACTOR = True

    try:
        sys.stdout = SafeStreamWrapper(sys.stdout)
        sys.stderr = SafeStreamWrapper(sys.stderr)
    except Exception:
        pass


def sanitize_filename(filename: str) -> str:
    """Prevents path traversal and unwanted characters in uploaded script filenames."""
    raw_name = Path(filename).name
    stem = Path(raw_name).stem
    suffix = Path(raw_name).suffix.lower()

    if suffix not in (".lua", ".luau", ".txt"):
        suffix = ".lua"

    clean_stem = re.sub(r'[^a-zA-Z0-9_\-]', '_', stem)[:40]
    if not clean_stem:
        clean_stem = "script"

    return f"{clean_stem}{suffix}"


def scan_script_safety(content: str) -> Tuple[bool, str]:
    """Scans Lua code for host-level OS compromise or token theft patterns."""
    if not content:
        return True, ""

    detected_threats = []
    for pattern, threat_desc in DANGEROUS_LUA_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            detected_threats.append(threat_desc)

    if detected_threats:
        reason = "ตรวจพบคำสั่งที่มีความเสี่ยงต่อระบบความปลอดภัยของโฮสต์:\n• " + "\n• ".join(detected_threats[:4])
        return False, reason

    return True, ""


# Sandbox Preamble for executing untrusted Lua inside worker runtimes
LUA_SANDBOX_PREAMBLE = """
-- =========================================================================
-- 🛡️ PAYOMBØYZ HARDENED HOST SECURITY SANDBOX
-- Blocks host OS escape, malicious subprocess execution, and token theft
-- =========================================================================
local _raw_os = os or {}
os = {
    clock = _raw_os.clock or function() return 0 end,
    date = _raw_os.date or function() return "" end,
    difftime = _raw_os.difftime or function() return 0 end,
    time = _raw_os.time or function() return 0 end,
    getenv = function(k) return nil end,
    execute = function(...) error("[SECURITY BLOCKED] os.execute is disabled.") end,
    remove = function(...) error("[SECURITY BLOCKED] os.remove is disabled.") end,
    rename = function(...) error("[SECURITY BLOCKED] os.rename is disabled.") end,
    exit = function(...) error("[SECURITY BLOCKED] os.exit is disabled.") end,
    setlocale = _raw_os.setlocale or function() return "C" end,
}
io = {
    popen = function(...) error("[SECURITY BLOCKED] io.popen is disabled.") end,
    open = function(...) error("[SECURITY BLOCKED] io.open is disabled.") end,
    lines = function(...) error("[SECURITY BLOCKED] io.lines is disabled.") end,
    close = function() end,
    type = function() return nil end,
}
package = {
    loaded = package and package.loaded or {},
    preload = package and package.preload or {},
    loadlib = function(...) error("[SECURITY BLOCKED] package.loadlib is disabled.") end,
    cpath = "",
    path = "",
}
dofile = function(...) error("[SECURITY BLOCKED] dofile is disabled.") end
loadfile = function(...) error("[SECURITY BLOCKED] loadfile is disabled.") end
if debug then
    debug.debug = nil
    debug.getfenv = nil
    debug.setfenv = nil
end
-- =========================================================================
"""
