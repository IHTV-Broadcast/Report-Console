"""
Telegram Bot Dispatcher Module (Private Message / PV Mode).
Handles asynchronous private message dispatch to Admin and selected staff,
individual per-recipient delivery tracking, error reporting, and idempotent retries.
"""

import os
import html
import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("telegram_dispatcher")

def get_telegram_bot_token(db_conn) -> str:
    """Reads Telegram Bot Token from DB settings or .env file."""
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'telegram_bot_token'")
    token_row = cursor.fetchone()
    token = (token_row["value"] if token_row and token_row["value"] else os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    return token

def get_admin_telegram_id(db_conn) -> Optional[str]:
    """Reads Admin numeric Telegram User ID from DB settings, users table, or .env file (Strictly PV, no groups)."""
    cursor = db_conn.cursor()
    # 1. From settings table (takes priority when explicitly configured in Admin panel)
    cursor.execute("SELECT value FROM settings WHERE key = 'admin_telegram_id'")
    st_row = cursor.fetchone()
    if st_row and st_row["value"]:
        val = str(st_row["value"]).strip()
        if not val.startswith("-"):
            return val

    # 2. From Admin user row in users table (RAL is unified Admin)
    cursor.execute("SELECT telegram_id FROM users WHERE (role = 'Admin' OR name = 'RAL') AND is_active = 1 LIMIT 1")
    u_row = cursor.fetchone()
    if u_row and u_row["telegram_id"]:
        val = str(u_row["telegram_id"]).strip()
        if not val.startswith("-"):
            return val

    # 3. From environment variable (only positive numeric user IDs)
    env_id = (os.getenv("ADMIN_TELEGRAM_USER_ID", "") or os.getenv("ADMIN_TELEGRAM_ID", "")).strip()
    if env_id and not env_id.startswith("-"):
        return env_id

    return "858324589"

def get_telegram_config(db_conn) -> tuple:
    """Returns bot token and Admin telegram ID for backwards compatibility."""
    token = get_telegram_bot_token(db_conn)
    admin_id = get_admin_telegram_id(db_conn)
    return token, admin_id or ""

def format_private_incident_alert(
    report_dict: Dict[str, Any],
    mentions: List[Dict[str, Any]],
    portal_base_url: str = "http://localhost:3006"
) -> str:
    """
    Constructs a clean HTML-formatted private Telegram alert.
    Displays real incident data without report numbers or portal links,
    with full Unicode Persian/English support and clean mobile typography.
    """
    unit = html.escape(str(report_dict.get("unit_name", "-")))
    sec_raw = report_dict.get("section_name")
    sec_clean = str(sec_raw).strip() if sec_raw else ""
    has_distinct_section = bool(sec_clean and sec_clean not in ["-", "None", "null", unit])
    section_line = f"\n📂 <b>Section:</b> {html.escape(sec_clean)}" if has_distinct_section else ""
    reporter = html.escape(str(report_dict.get("reporter_name", "Anonymous")))
    preset = report_dict.get("preset_tag")
    description = html.escape(str(report_dict.get("description", "")).strip())
    priority_raw = str(report_dict.get("priority", "Normal")).strip()
    is_critical = priority_raw.upper() == "CRITICAL"
    prio_display = "Critical" if is_critical else "Normal"
    prio_icon = "🔴" if is_critical else "🟡"
    header_icon = "🚨" if is_critical else "📢"
    created_at = report_dict.get("created_at", "")[:19].replace("T", " ")

    category_line = f"\n📂 <b>Category:</b> <code>{html.escape(preset)}</code>" if preset else ""

    # Extra mentions list
    extra_names = [html.escape(m.get("name", "Staff")) for m in mentions]
    mentions_line = f"\n👥 <b>Recipients:</b> {', '.join(extra_names)}" if extra_names else ""

    msg = (
        f"{header_icon} <b>New Incident Notification</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <b>Priority:</b> {prio_icon} <b>{prio_display}</b>\n"
        f"🏢 <b>Unit:</b> {unit}{section_line}{category_line}\n"
        f"👤 <b>Reporter:</b> {reporter}\n"
        f"🕒 <b>Date & Time:</b> <code>{created_at}</code>{mentions_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>Description:</b>\n"
        f"{description}"
    )
    return msg

# Backwards compatibility alias
format_telegram_alert = lambda report_dict, managers, mentions, portal_base_url="http://localhost:3006": format_private_incident_alert(report_dict, mentions, portal_base_url)

async def send_telegram_private_message(token: str, chat_id: str, text: str) -> Dict[str, Any]:
    """
    Sends HTML message to a private user chat via Telegram Bot API using httpx async client.
    Handles Telegram Bot PV constraints (e.g. 403 user hasn't started the bot).
    """
    if not token:
        return {"ok": False, "error": "Telegram Bot Token is not configured."}
    if not chat_id:
        return {"ok": False, "error": "Telegram User ID is missing."}

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(api_url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return {
                    "ok": True,
                    "message_id": data.get("result", {}).get("message_id")
                }
            else:
                desc = data.get("description", resp.text)
                if resp.status_code == 403 or "bot can't initiate conversation" in desc.lower():
                    err_msg = "Telegram Error (403): User has not started the bot yet. Recipient must open the bot and press /start."
                elif resp.status_code == 400 and "chat not found" in desc.lower():
                    err_msg = "Telegram Error (400): Chat not found. Invalid Telegram User ID."
                elif resp.status_code == 403 and "blocked" in desc.lower():
                    err_msg = "Telegram Error (403): Bot was blocked by the user."
                else:
                    err_msg = f"Telegram API Error ({resp.status_code}): {desc}"
                return {"ok": False, "error": err_msg}
    except Exception as e:
        return {"ok": False, "error": f"Connection error: {str(e)}"}

# Backwards compatibility alias
send_telegram_message = send_telegram_private_message
