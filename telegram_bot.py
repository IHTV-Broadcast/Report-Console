"""
Telegram Bot Engine for Corporate Incident Reporting (English Interface).

Exact 7-step reporting workflow:
1. Select Reporter: "Who is submitting this report?" (Dynamic active staff, excluding admin and special options)
2. Select Unit: "Which unit is affected?" (Dynamic active units)
3. Select Category (Only if applicable): "What is the issue?" (Auto-skipped if unit has no categories)
4. Select Urgency: "How urgent is it?" (Exactly Critical and Normal)
5. Describe Issue: "Briefly describe the issue." (Free-text, accepts English/Persian/mixed Unicode)
6. Select Recipients: "Who else should receive this report?" (Multi-select toggles, Done, Clear selection)
7. Review & Submit: Concise summary with Submit, Back, Cancel -> "Report submitted. ID: #INC-XXXXX"
"""

import os
import json
import html
import asyncio
import logging
import secrets
import string
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

import httpx
from database import get_connection
from telegram_dispatcher import (
    get_telegram_bot_token,
    get_admin_telegram_id,
    send_telegram_private_message
)

logger = logging.getLogger("telegram_bot")

# Conversation States
STATE_IDLE = "IDLE"
STATE_SELECT_REPORTER = "SELECT_REPORTER"
STATE_SELECT_UNIT = "SELECT_UNIT"
STATE_SELECT_CATEGORY = "SELECT_CATEGORY"
STATE_SELECT_URGENCY = "SELECT_URGENCY"
STATE_ENTER_DESCRIPTION = "ENTER_DESCRIPTION"
STATE_SELECT_RECIPIENTS = "SELECT_RECIPIENTS"
STATE_CONFIRM_REPORT = "CONFIRM_REPORT"

# Excluded non-employee names from UI selection
EXCLUDED_USER_NAMES = {
    "RAL", "ADMIN", "ADMINISTRATOR",
    "TEST ENGINEER", "COLLEAGUE",
    "مهندس تست", "همکار رونوشت", "کاربر مهمان تلگرام"
}

# --- Database State & Deduplication Helpers ---

def get_conversation(chat_id: str) -> Dict[str, Any]:
    """Retrieves current bot conversation state for a chat ID, or returns default idle state."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT chat_id, user_id, reporter_name, state, data_json, last_message_id, updated_at
        FROM telegram_bot_conversations
        WHERE chat_id = ?
    """, (str(chat_id),))
    row = cursor.fetchone()
    conn.close()

    if row:
        data = {}
        try:
            data = json.loads(row["data_json"] or "{}")
        except Exception:
            data = {}
        return {
            "chat_id": str(row["chat_id"]),
            "user_id": row["user_id"],
            "reporter_name": row["reporter_name"],
            "state": row["state"] or STATE_IDLE,
            "data": data,
            "last_message_id": row["last_message_id"]
        }
    return {
        "chat_id": str(chat_id),
        "user_id": None,
        "reporter_name": None,
        "state": STATE_IDLE,
        "data": {},
        "last_message_id": None
    }

def save_conversation(conv: Dict[str, Any]):
    """Persists conversation state to database."""
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    data_json = json.dumps(conv.get("data", {}), ensure_ascii=False)
    cursor.execute("""
        INSERT OR REPLACE INTO telegram_bot_conversations
        (chat_id, user_id, reporter_name, state, data_json, last_message_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        str(conv["chat_id"]),
        conv.get("user_id"),
        conv.get("reporter_name"),
        conv.get("state", STATE_IDLE),
        data_json,
        conv.get("last_message_id"),
        now_iso
    ))
    conn.commit()
    conn.close()

def clear_conversation(chat_id: str):
    """Resets conversation state to IDLE."""
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    cursor.execute("""
        UPDATE telegram_bot_conversations
        SET state = ?, data_json = '{}', updated_at = ?
        WHERE chat_id = ?
    """, (STATE_IDLE, now_iso, str(chat_id)))
    conn.commit()
    conn.close()

def is_update_processed(update_id: int) -> bool:
    """Checks whether an update has already been processed to prevent duplicates."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT update_id FROM telegram_processed_updates WHERE update_id = ?", (update_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row)

def mark_update_processed(update_id: int):
    """Marks an update as processed."""
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    cursor.execute("INSERT OR IGNORE INTO telegram_processed_updates (update_id, processed_at) VALUES (?, ?)", (update_id, now_iso))
    conn.commit()
    conn.close()

# --- Telegram Bot API Helpers ---

async def bot_send_message(
    token: str,
    chat_id: str,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Sends a Telegram message with optional inline keyboard."""
    if not token:
        return {"ok": False, "error": "Bot token not configured"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.json()
    except Exception as e:
        logger.error(f"Error sending bot message: {e}")
        return {"ok": False, "error": str(e)}

async def bot_edit_message(
    token: str,
    chat_id: str,
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Edits an existing Telegram message."""
    if not token or not message_id:
        return await bot_send_message(token, chat_id, text, reply_markup)
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if not data.get("ok"):
                return await bot_send_message(token, chat_id, text, reply_markup)
            return data
    except Exception as e:
        logger.error(f"Error editing bot message: {e}")
        return await bot_send_message(token, chat_id, text, reply_markup)

async def bot_answer_callback(
    token: str,
    callback_query_id: str,
    text: Optional[str] = None,
    show_alert: bool = False
) -> Dict[str, Any]:
    """Acknowledges an inline keyboard callback query."""
    if not token or not callback_query_id:
        return {"ok": False}
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
    if text:
        payload["text"] = text
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            return resp.json()
    except Exception as e:
        logger.warning(f"Error answering callback query: {e}")
        return {"ok": False, "error": str(e)}

# --- Dynamic System Data Retrieval ---

def fetch_eligible_reporters() -> List[Dict[str, Any]]:
    """
    Fetches active, eligible employees for reporter selection.
    Strictly excludes the admin account (RAL) and special test options.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, role
        FROM users
        WHERE is_active = 1
          AND role != 'Admin'
        ORDER BY name ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Filter out RAL and excluded test aliases
    filtered = [
        r for r in rows
        if r["name"].strip().upper() not in EXCLUDED_USER_NAMES
    ]
    return filtered

def fetch_active_units() -> List[Dict[str, Any]]:
    """Fetches all active units from system database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, sort_order FROM units WHERE is_active = 1 ORDER BY sort_order ASC, name ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def fetch_active_categories_for_unit(unit_id: Optional[int]) -> List[Dict[str, Any]]:
    """Fetches active issue categories applicable to the selected unit or global."""
    conn = get_connection()
    cursor = conn.cursor()
    if unit_id:
        cursor.execute("""
            SELECT id, name, unit_id, sort_order
            FROM issue_categories
            WHERE is_active = 1 AND (unit_id IS NULL OR unit_id = ?)
            ORDER BY sort_order ASC, name ASC
        """, (unit_id,))
    else:
        cursor.execute("""
            SELECT id, name, unit_id, sort_order
            FROM issue_categories
            WHERE is_active = 1
            ORDER BY sort_order ASC, name ASC
        """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def fetch_eligible_recipients(reporter_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Fetches active, eligible employees for additional CC recipients.
    Excludes the admin account (RAL is automatically notified), the reporter themselves,
    and special test options.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, role, telegram_id
        FROM users
        WHERE is_active = 1
          AND role != 'Admin'
        ORDER BY name ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    filtered = [
        r for r in rows
        if r["name"].strip().upper() not in EXCLUDED_USER_NAMES
        and (reporter_id is None or r["id"] != reporter_id)
    ]
    return filtered

# --- Workflow Step Renderers ---

def build_welcome_menu() -> Tuple[str, Dict[str, Any]]:
    """Builds the main menu in English."""
    text = (
        "🔔 <b>Welcome to Incident Reporter.</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Quickly submit technical incidents and notify the response team.\n\n"
        "Tap below to begin:"
    )
    keyboard = {
        "inline_keyboard": [
            [{"text": "Start Report", "callback_data": "start_new_report"}]
        ]
    }
    return text, keyboard

def build_reporter_step() -> Tuple[str, Dict[str, Any]]:
    """Step 1: Select Reporter."""
    employees = fetch_eligible_reporters()
    text = (
        "👤 <b>Who is submitting this report?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please select your name from the active list:"
    )
    buttons = []
    row = []
    for emp in employees:
        row.append({"text": emp["name"], "callback_data": f"rep_{emp['id']}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([{"text": "Cancel", "callback_data": "cancel_report"}])
    return text, {"inline_keyboard": buttons}

def build_unit_step() -> Tuple[str, Dict[str, Any]]:
    """Step 2: Select Unit."""
    units = fetch_active_units()
    text = (
        "🏢 <b>Which unit is affected?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select the affected operational unit or department:"
    )
    buttons = []
    row = []
    for u in units:
        row.append({"text": u["name"], "callback_data": f"unit_{u['id']}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        {"text": "Back", "callback_data": "back_to_reporter"},
        {"text": "Cancel", "callback_data": "cancel_report"}
    ])
    return text, {"inline_keyboard": buttons}

def build_category_step(unit_id: int) -> Tuple[str, Dict[str, Any]]:
    """Step 3: Select Category (only if applicable)."""
    categories = fetch_active_categories_for_unit(unit_id)
    text = (
        "📂 <b>What is the issue?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select the relevant issue category:"
    )
    buttons = []
    row = []
    for cat in categories:
        row.append({"text": cat["name"], "callback_data": f"cat_{cat['id']}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        {"text": "Back", "callback_data": "back_to_unit"},
        {"text": "Cancel", "callback_data": "cancel_report"}
    ])
    return text, {"inline_keyboard": buttons}

def build_urgency_step(back_callback: str = "back_to_unit") -> Tuple[str, Dict[str, Any]]:
    """Step 4: Select Urgency (Critical or Normal)."""
    text = (
        "⚡ <b>How urgent is it?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "• <b>Critical</b> — Service outage or major technical disruption\n"
        "• <b>Normal</b> — Minor issue or operational inquiry"
    )
    buttons = [
        [
            {"text": "Critical", "callback_data": "urg_critical"},
            {"text": "Normal", "callback_data": "urg_normal"}
        ],
        [
            {"text": "Back", "callback_data": back_callback},
            {"text": "Cancel", "callback_data": "cancel_report"}
        ]
    ]
    return text, {"inline_keyboard": buttons}

def build_description_step() -> Tuple[str, Dict[str, Any]]:
    """Step 5: Describe Issue."""
    text = (
        "📝 <b>Briefly describe the issue.</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Type your message below and send it. You may include error codes, channels, or details in English or Persian."
    )
    buttons = [
        [
            {"text": "Back", "callback_data": "back_to_urgency"},
            {"text": "Cancel", "callback_data": "cancel_report"}
        ]
    ]
    return text, {"inline_keyboard": buttons}

def build_recipients_step(reporter_id: Optional[int], selected_ids: List[int]) -> Tuple[str, Dict[str, Any]]:
    """Step 6: Select Recipients."""
    eligible = fetch_eligible_recipients(reporter_id)
    selected_set = set(selected_ids)
    text = (
        "👥 <b>Who else should receive this report?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select team members to receive private notifications (optional):"
    )

    buttons = []
    row = []
    for emp in eligible:
        is_sel = emp["id"] in selected_set
        icon = "✅" if is_sel else "⚪"
        row.append({"text": f"{icon} {emp['name']}", "callback_data": f"rec_toggle_{emp['id']}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Action buttons: Done, Clear selection
    buttons.append([
        {"text": "Done", "callback_data": "rec_done"},
        {"text": "Clear selection", "callback_data": "rec_clear"}
    ])
    buttons.append([
        {"text": "Back", "callback_data": "back_to_description"},
        {"text": "Cancel", "callback_data": "cancel_report"}
    ])

    return text, {"inline_keyboard": buttons}

def build_summary_step(conv: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Step 7: Review and Submit."""
    d = conv.get("data", {})
    reporter = d.get("reporter_name", "-")
    unit = d.get("unit_name", "-")
    category = d.get("preset_tag")
    urgency = d.get("urgency", "Normal")
    description = d.get("description", "")
    cc_ids = d.get("selected_recipients", [])

    prio_icon = "🔴" if str(urgency).upper() == "CRITICAL" else "🟡"

    lines = [
        "📋 <b>Please review your report:</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"👤 <b>Reporter:</b> {html.escape(reporter)}",
        f"🏢 <b>Unit:</b> {html.escape(unit)}"
    ]
    if category:
        lines.append(f"📂 <b>Category:</b> {html.escape(category)}")
    lines.append(f"⚡ <b>Urgency:</b> {prio_icon} {html.escape(urgency)}")
    lines.append(f"📝 <b>Description:</b>\n{html.escape(description)}")

    if cc_ids:
        all_staff = {u["id"]: u["name"] for u in fetch_eligible_recipients()}
        names = [all_staff[cid] for cid in cc_ids if cid in all_staff]
        if names:
            lines.append(f"👥 <b>Additional recipients:</b> {html.escape(', '.join(names))}")

    text = "\n".join(lines)
    buttons = [
        [{"text": "Submit", "callback_data": "submit_final_report"}],
        [
            {"text": "Back", "callback_data": "back_to_recipients"},
            {"text": "Cancel", "callback_data": "cancel_report"}
        ]
    ]
    return text, {"inline_keyboard": buttons}

# --- Configuration Validation & Mid-Session Synchronization ---

def validate_report_configuration(conv: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    """
    Validates that reporter, unit, category, and recipients are still active in the database.
    Ensures that any mid-session deactivations or deletions made in the Admin panel
    prevent submission of invalid reports and guide the user to select active replacements.

    Returns:
      (True, None, None, None) if completely valid.
      (False, invalid_step, error_message, keyboard) if an entity became inactive.
    """
    d = conv.get("data", {})
    reporter_id = d.get("reporter_id")
    unit_id = d.get("unit_id")
    preset_tag = d.get("preset_tag")
    selected_recipients = d.get("selected_recipients", [])

    conn = get_connection()
    cursor = conn.cursor()

    # 1. Validate Reporter
    if not reporter_id:
        conn.close()
        txt, kb = build_reporter_step()
        return False, STATE_SELECT_REPORTER, "Please select an active reporter.", kb

    cursor.execute("SELECT id, name, role, is_active FROM users WHERE id = ?", (reporter_id,))
    rep_row = cursor.fetchone()
    if not rep_row or rep_row["is_active"] != 1 or rep_row["role"] == "Admin" or rep_row["name"].strip().upper() in EXCLUDED_USER_NAMES:
        conn.close()
        conv["user_id"] = None
        conv["reporter_name"] = None
        d["reporter_id"] = None
        d["reporter_name"] = None
        conv["state"] = STATE_SELECT_REPORTER
        save_conversation(conv)
        txt, kb = build_reporter_step()
        return False, STATE_SELECT_REPORTER, f"⚠️ <b>The selected reporter is no longer active.</b>\n\n{txt}", kb

    # 2. Validate Unit
    if not unit_id:
        conn.close()
        txt, kb = build_unit_step()
        return False, STATE_SELECT_UNIT, "Please select an active unit.", kb

    cursor.execute("SELECT id, name, is_active FROM units WHERE id = ?", (unit_id,))
    unit_row = cursor.fetchone()
    if not unit_row or unit_row["is_active"] != 1:
        conn.close()
        d["unit_id"] = None
        d["unit_name"] = None
        d["preset_tag"] = None
        conv["state"] = STATE_SELECT_UNIT
        save_conversation(conv)
        txt, kb = build_unit_step()
        return False, STATE_SELECT_UNIT, f"⚠️ <b>The selected unit is no longer active.</b>\n\n{txt}", kb

    # 3. Validate Category (if selected or applicable)
    active_cats = fetch_active_categories_for_unit(unit_id)
    if preset_tag:
        matching_cat = next((c for c in active_cats if c["name"] == preset_tag), None)
        if not matching_cat:
            if active_cats:
                d["preset_tag"] = None
                conv["state"] = STATE_SELECT_CATEGORY
                save_conversation(conv)
                txt, kb = build_category_step(unit_id)
                conn.close()
                return False, STATE_SELECT_CATEGORY, f"⚠️ <b>The selected category is no longer active.</b>\n\n{txt}", kb
            else:
                # No active categories remain for this unit -> automatically clear category
                d["preset_tag"] = None
                conv["data"]["preset_tag"] = None
                conv["data"]["has_categories"] = False

    # 4. Validate & Prune Recipients
    if selected_recipients:
        cursor.execute("""
            SELECT id FROM users
            WHERE is_active = 1 AND role != 'Admin' AND id != ?
        """, (reporter_id,))
        active_recip_ids = {r["id"] for r in cursor.fetchall()}
        valid_recips = [uid for uid in selected_recipients if uid in active_recip_ids]
        d["selected_recipients"] = valid_recips
        conv["data"]["selected_recipients"] = valid_recips

    conn.close()
    return True, None, None, None

# --- Report Submission ---

async def finalize_telegram_report_submission(
    token: str,
    chat_id: str,
    conv: Dict[str, Any],
    update_id: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Commits report to database with source='Telegram' and initiates private notifications.
    Strictly PV only to Admin (RAL) and selected staff. Never sends to groups or channels.
    Validates current active configuration before committing to handle mid-session changes.
    """
    # Mid-session validation check
    is_valid, invalid_step, err_msg, kb = validate_report_configuration(conv)
    if not is_valid:
        last_msg_id = conv.get("last_message_id")
        if last_msg_id:
            await bot_edit_message(token, chat_id, last_msg_id, err_msg, kb)
        else:
            await bot_send_message(token, chat_id, err_msg, kb)
        return False, ""

    conn = get_connection()
    cursor = conn.cursor()
    d = conv.get("data", {})

    unit_id = d.get("unit_id")
    unit_name = d.get("unit_name", "General")
    reporter_name = d.get("reporter_name", "Reporter")
    reporter_id = d.get("reporter_id")
    preset_tag = d.get("preset_tag")
    description = d.get("description", "").strip() or "Incident reported via Telegram."
    priority = d.get("urgency", "Normal")
    extra_mention_ids = d.get("selected_recipients", [])

    # Generate unique readable tracking code (e.g. INC-26-84920)
    year_prefix = datetime.now().strftime("%y")
    tracking_code = None
    for _ in range(10):
        rand_suffix = ''.join(secrets.choice(string.digits) for _ in range(5))
        cand_code = f"INC-{year_prefix}-{rand_suffix}"
        cursor.execute("SELECT id FROM reports WHERE tracking_code = ?", (cand_code,))
        if not cursor.fetchone():
            tracking_code = cand_code
            break
    if not tracking_code:
        tracking_code = f"INC-{year_prefix}-{secrets.token_hex(3).upper()}"

    now_iso = datetime.now().isoformat()

    # Insert into reports table
    cursor.execute("""
        INSERT INTO reports (
            tracking_code, reporter_name, reporter_id, unit_id, unit_name,
            section_id, section_name, preset_tag, description, priority,
            status, source, telegram_chat_id, telegram_update_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, 'Pending', 'Telegram', ?, ?, ?, ?)
    """, (
        tracking_code, reporter_name, reporter_id, unit_id, unit_name,
        preset_tag, description, priority, str(chat_id), update_id,
        now_iso, now_iso
    ))
    report_id = cursor.lastrowid

    # Insert report mentions
    mentions_to_log = []
    if extra_mention_ids:
        for uid in set(extra_mention_ids):
            cursor.execute("SELECT id, name, telegram_id FROM users WHERE id = ? AND is_active = 1", (uid,))
            u_mention = cursor.fetchone()
            if u_mention:
                cursor.execute("""
                    INSERT OR IGNORE INTO report_mentions (report_id, user_id, user_name)
                    VALUES (?, ?, ?)
                """, (report_id, uid, u_mention["name"]))
                mentions_to_log.append(dict(u_mention))

    # Resolve Primary Recipient: Admin (RAL)
    cursor.execute("SELECT id, name, telegram_id FROM users WHERE (role = 'Admin' OR name = 'RAL') AND is_active = 1 LIMIT 1")
    admin_u = cursor.fetchone()
    admin_user_id = admin_u["id"] if admin_u else None
    admin_name = admin_u["name"] if admin_u else "RAL"
    admin_tg_id = (admin_u["telegram_id"] if admin_u and admin_u["telegram_id"] else None) or "858324589"

    # 1. Admin (RAL) PV Alert
    cursor.execute("""
        INSERT INTO dispatch_logs (report_id, recipient_role, user_id, user_name, telegram_id, status, attempted_at)
        VALUES (?, 'ADMIN', ?, ?, ?, 'PENDING', ?)
    """, (report_id, admin_user_id, admin_name, admin_tg_id, now_iso))

    # 2. Selected recipients PV Alerts (never to groups)
    for m in mentions_to_log:
        if admin_user_id and m["id"] == admin_user_id:
            continue
        if admin_tg_id and m.get("telegram_id") and str(m["telegram_id"]).strip() == str(admin_tg_id).strip():
            continue
        cursor.execute("""
            INSERT INTO dispatch_logs (report_id, recipient_role, user_id, user_name, telegram_id, status, attempted_at)
            VALUES (?, 'MENTION', ?, ?, ?, 'PENDING', ?)
        """, (report_id, m["id"], m["name"], m.get("telegram_id"), now_iso))

    conn.commit()
    conn.close()

    # Clear conversation state
    clear_conversation(chat_id)

    # Deliver alerts asynchronously via dispatch helper
    from main import dispatch_report_to_telegram
    asyncio.create_task(dispatch_report_to_telegram(report_id))

    # Output confirmation message without report number or ID
    success_text = (
        "✅ <b>Report submitted.</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Your incident report has been registered successfully and dispatched to the response team."
    )
    receipt_keyboard = {
        "inline_keyboard": [
            [{"text": "Start New Report", "callback_data": "start_new_report"}]
        ]
    }
    await bot_send_message(token, chat_id, success_text, receipt_keyboard)
    return True, tracking_code

# --- Core Update Processing Engine ---

async def process_telegram_update(update: Dict[str, Any], token: Optional[str] = None):
    """
    Main entry point for incoming Telegram updates.
    Ensures deduplication, strict state transitions, and English-only interaction.
    """
    update_id = update.get("update_id")
    if not update_id:
        return

    # Deduplication check
    if is_update_processed(update_id):
        logger.debug(f"Skipping duplicate update {update_id}")
        return
    mark_update_processed(update_id)

    if not token:
        conn = get_connection()
        token = get_telegram_bot_token(conn)
        conn.close()

    if not token or token == "123456:FAKE_TOKEN":
        return

    # Case 1: Callback Query (Inline Button Click)
    if "callback_query" in update:
        cq = update["callback_query"]
        cq_id = cq.get("id")
        cb_data = cq.get("data", "")
        from_user = cq.get("from", {})
        user_tg_id = str(from_user.get("id", ""))
        message = cq.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", user_tg_id))
        msg_id = message.get("message_id")

        await bot_answer_callback(token, cq_id)

        conv = get_conversation(chat_id)
        conv["last_message_id"] = msg_id

        # Cancel action
        if cb_data == "cancel_report":
            clear_conversation(chat_id)
            kb = {"inline_keyboard": [[{"text": "Start Report", "callback_data": "start_new_report"}]]}
            await bot_edit_message(token, chat_id, msg_id, "❌ <b>Report cancelled.</b>\n\nYou can start a new report at any time.", kb)
            return

        # Start new report (Every new report begins with Step 1: Reporter selection)
        if cb_data == "start_new_report":
            conv["state"] = STATE_SELECT_REPORTER
            conv["data"] = {}
            conv["user_id"] = None
            conv["reporter_name"] = None
            save_conversation(conv)
            txt, kb = build_reporter_step()
            await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Step 1: Reporter Selected
        if cb_data.startswith("rep_"):
            try:
                rep_id = int(cb_data.replace("rep_", ""))
                employees = fetch_eligible_reporters()
                chosen = next((e for e in employees if e["id"] == rep_id), None)
                if not chosen:
                    txt, kb = build_reporter_step()
                    await bot_edit_message(token, chat_id, msg_id, f"⚠️ <b>The selected reporter is no longer active.</b>\n\n{txt}", kb)
                    return
                conv["user_id"] = chosen["id"]
                conv["reporter_name"] = chosen["name"]
                conv["data"] = {
                    "reporter_id": chosen["id"],
                    "reporter_name": chosen["name"]
                }
                conv["state"] = STATE_SELECT_UNIT
                save_conversation(conv)
                txt, kb = build_unit_step()
                await bot_edit_message(token, chat_id, msg_id, txt, kb)
            except Exception as e:
                logger.error(f"Error selecting reporter: {e}")
            return

        # Back to Reporter
        if cb_data == "back_to_reporter":
            conv["state"] = STATE_SELECT_REPORTER
            save_conversation(conv)
            txt, kb = build_reporter_step()
            await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Step 2: Unit Selected
        if cb_data.startswith("unit_"):
            try:
                u_id = int(cb_data.replace("unit_", ""))
                units = fetch_active_units()
                chosen_u = next((u for u in units if u["id"] == u_id), None)
                if not chosen_u:
                    txt, kb = build_unit_step()
                    await bot_edit_message(token, chat_id, msg_id, f"⚠️ <b>The selected unit is no longer active.</b>\n\n{txt}", kb)
                    return
                conv["data"]["unit_id"] = chosen_u["id"]
                conv["data"]["unit_name"] = chosen_u["name"]

                # Step 3: Check if unit has active categories
                categories = fetch_active_categories_for_unit(chosen_u["id"])
                if categories:
                    conv["data"]["has_categories"] = True
                    conv["state"] = STATE_SELECT_CATEGORY
                    save_conversation(conv)
                    txt, kb = build_category_step(chosen_u["id"])
                    await bot_edit_message(token, chat_id, msg_id, txt, kb)
                else:
                    # Skip Category step automatically
                    conv["data"]["has_categories"] = False
                    conv["data"]["preset_tag"] = None
                    conv["state"] = STATE_SELECT_URGENCY
                    save_conversation(conv)
                    txt, kb = build_urgency_step(back_callback="back_to_unit")
                    await bot_edit_message(token, chat_id, msg_id, txt, kb)
            except Exception as e:
                logger.error(f"Error selecting unit: {e}")
            return

        # Back to Unit
        if cb_data == "back_to_unit":
            conv["state"] = STATE_SELECT_UNIT
            save_conversation(conv)
            txt, kb = build_unit_step()
            await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Step 3: Category Selected
        if cb_data.startswith("cat_"):
            try:
                cat_id = int(cb_data.replace("cat_", ""))
                categories = fetch_active_categories_for_unit(conv["data"].get("unit_id"))
                chosen_cat = next((c for c in categories if c["id"] == cat_id), None)
                if not chosen_cat:
                    if categories:
                        txt, kb = build_category_step(conv["data"].get("unit_id"))
                        await bot_edit_message(token, chat_id, msg_id, f"⚠️ <b>The selected category is no longer active.</b>\n\n{txt}", kb)
                        return
                    else:
                        conv["data"]["preset_tag"] = None
                        conv["data"]["has_categories"] = False
                        conv["state"] = STATE_SELECT_URGENCY
                        save_conversation(conv)
                        txt, kb = build_urgency_step(back_callback="back_to_unit")
                        await bot_edit_message(token, chat_id, msg_id, txt, kb)
                        return

                conv["data"]["preset_tag"] = chosen_cat["name"]
                conv["state"] = STATE_SELECT_URGENCY
                save_conversation(conv)
                txt, kb = build_urgency_step(back_callback="back_to_category")
                await bot_edit_message(token, chat_id, msg_id, txt, kb)
            except Exception as e:
                logger.error(f"Error selecting category: {e}")
            return

        # Back to Category
        if cb_data == "back_to_category":
            unit_id = conv["data"].get("unit_id")
            categories = fetch_active_categories_for_unit(unit_id)
            if categories:
                conv["state"] = STATE_SELECT_CATEGORY
                save_conversation(conv)
                txt, kb = build_category_step(unit_id)
                await bot_edit_message(token, chat_id, msg_id, txt, kb)
            else:
                conv["state"] = STATE_SELECT_UNIT
                save_conversation(conv)
                txt, kb = build_unit_step()
                await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Step 4: Urgency Selected (Critical / Normal)
        if cb_data in ["urg_critical", "urg_normal"]:
            conv["data"]["urgency"] = "Critical" if cb_data == "urg_critical" else "Normal"
            conv["state"] = STATE_ENTER_DESCRIPTION
            save_conversation(conv)
            txt, kb = build_description_step()
            await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Back to Urgency
        if cb_data == "back_to_urgency":
            conv["state"] = STATE_SELECT_URGENCY
            save_conversation(conv)
            unit_id = conv["data"].get("unit_id")
            has_cats = bool(fetch_active_categories_for_unit(unit_id)) if unit_id else False
            back_target = "back_to_category" if has_cats else "back_to_unit"
            txt, kb = build_urgency_step(back_callback=back_target)
            await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Back to Description
        if cb_data == "back_to_description":
            conv["state"] = STATE_ENTER_DESCRIPTION
            save_conversation(conv)
            txt, kb = build_description_step()
            await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Step 6: Recipient Toggle
        if cb_data.startswith("rec_toggle_"):
            try:
                target_uid = int(cb_data.replace("rec_toggle_", ""))
                eligible = fetch_eligible_recipients(conv["data"].get("reporter_id"))
                if not any(e["id"] == target_uid for e in eligible):
                    cur_sel = [x for x in conv["data"].get("selected_recipients", []) if any(e["id"] == x for e in eligible)]
                    conv["data"]["selected_recipients"] = cur_sel
                    save_conversation(conv)
                    txt, kb = build_recipients_step(conv["data"].get("reporter_id"), cur_sel)
                    await bot_edit_message(token, chat_id, msg_id, f"⚠️ <b>That recipient is no longer active.</b>\n\n{txt}", kb)
                    return

                selected = set(conv["data"].get("selected_recipients", []))
                if target_uid in selected:
                    selected.remove(target_uid)
                else:
                    selected.add(target_uid)
                conv["data"]["selected_recipients"] = list(selected)
                save_conversation(conv)
                txt, kb = build_recipients_step(conv["data"].get("reporter_id"), conv["data"]["selected_recipients"])
                await bot_edit_message(token, chat_id, msg_id, txt, kb)
            except Exception as e:
                logger.error(f"Error toggling recipient: {e}")
            return

        # Clear Selection
        if cb_data == "rec_clear":
            conv["data"]["selected_recipients"] = []
            save_conversation(conv)
            txt, kb = build_recipients_step(conv["data"].get("reporter_id"), [])
            await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Recipients Done -> Review Step
        if cb_data == "rec_done":
            conv["state"] = STATE_CONFIRM_REPORT
            save_conversation(conv)
            txt, kb = build_summary_step(conv)
            await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Back to Recipients
        if cb_data == "back_to_recipients":
            conv["state"] = STATE_SELECT_RECIPIENTS
            save_conversation(conv)
            txt, kb = build_recipients_step(conv["data"].get("reporter_id"), conv["data"].get("selected_recipients", []))
            await bot_edit_message(token, chat_id, msg_id, txt, kb)
            return

        # Step 7: Final Submit
        if cb_data == "submit_final_report":
            # Protect against repeated taps or stale clicks
            if conv.get("state") != STATE_CONFIRM_REPORT:
                await bot_answer_callback(token, cq_id, "⚠️ This report has already been processed.", show_alert=True)
                return
            await finalize_telegram_report_submission(token, chat_id, conv, update_id)
            return

    # Case 2: Regular Text Message
    elif "message" in update:
        msg = update["message"]
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "").strip()

        conv = get_conversation(chat_id)

        # Commands
        if text.startswith("/start"):
            clear_conversation(chat_id)
            txt, kb = build_welcome_menu()
            await bot_send_message(token, chat_id, txt, kb)
            return

        if text.startswith("/report"):
            conv["state"] = STATE_SELECT_REPORTER
            conv["data"] = {}
            conv["user_id"] = None
            conv["reporter_name"] = None
            save_conversation(conv)
            txt, kb = build_reporter_step()
            res = await bot_send_message(token, chat_id, txt, kb)
            conv["last_message_id"] = res.get("result", {}).get("message_id")
            save_conversation(conv)
            return

        if text.startswith("/cancel"):
            clear_conversation(chat_id)
            kb = {"inline_keyboard": [[{"text": "Start Report", "callback_data": "start_new_report"}]]}
            await bot_send_message(token, chat_id, "❌ <b>Operation cancelled.</b>\n\nYou can start a new report at any time.", kb)
            return

        if text.startswith("/help"):
            help_text = (
                "ℹ️ <b>Incident Reporter Commands</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "• <b>/start</b> — Main menu\n"
                "• <b>/report</b> — Submit a new technical incident\n"
                "• <b>/cancel</b> — Cancel current report\n"
                "• <b>/help</b> — Show available commands"
            )
            await bot_send_message(token, chat_id, help_text)
            return

        # Step 5: Description Input
        if conv.get("state") == STATE_ENTER_DESCRIPTION:
            if not text:
                await bot_send_message(token, chat_id, "⚠️ <b>Description cannot be empty.</b>\n\nBriefly describe the issue.")
                return

            conv["data"]["description"] = text
            conv["state"] = STATE_SELECT_RECIPIENTS
            if "selected_recipients" not in conv["data"]:
                conv["data"]["selected_recipients"] = []
            save_conversation(conv)

            txt, kb = build_recipients_step(conv["data"].get("reporter_id"), conv["data"]["selected_recipients"])
            res = await bot_send_message(token, chat_id, txt, kb)
            conv["last_message_id"] = res.get("result", {}).get("message_id")
            save_conversation(conv)
            return

        # Fallback response for unhandled text
        txt, kb = build_welcome_menu()
        await bot_send_message(token, chat_id, f"ℹ️ <b>Please select an option to continue:</b>\n\n{txt}", kb)

# --- Background Long-Polling Worker & Bot Menu Synchronization ---

BOT_COMMANDS = [
    {"command": "start", "description": "Main menu"},
    {"command": "report", "description": "Submit a new incident report"},
    {"command": "cancel", "description": "Cancel current report"},
    {"command": "help", "description": "Show available commands"}
]

async def sync_telegram_bot_commands(token: str):
    """
    Configures Telegram bot commands, descriptions, and menu button strictly to English.
    Ensures that opening the Telegram bot Menu button displays English text only.
    """
    if not token or "FAKE" in token:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Set default commands in English
            await client.post(
                f"https://api.telegram.org/bot{token}/setMyCommands",
                json={"commands": BOT_COMMANDS}
            )
            # Explicitly set fa (Persian) locale commands to English as well to prevent Telegram client localization
            await client.post(
                f"https://api.telegram.org/bot{token}/setMyCommands",
                json={"commands": BOT_COMMANDS, "language_code": "fa"}
            )
            # Ensure menu button is set to show bot commands
            await client.post(
                f"https://api.telegram.org/bot{token}/setChatMenuButton",
                json={"menu_button": {"type": "commands"}}
            )
            # Set English descriptions
            await client.post(
                f"https://api.telegram.org/bot{token}/setMyDescription",
                json={"description": "Incident Reporting Bot — Submit and track technical incident reports."}
            )
            await client.post(
                f"https://api.telegram.org/bot{token}/setMyShortDescription",
                json={"short_description": "Submit and track technical incident reports."}
            )
            logger.info("Telegram bot commands and menu button successfully synchronized to English.")
    except Exception as e:
        logger.warning(f"Failed to synchronize Telegram bot commands: {e}")

async def telegram_polling_loop():
    """
    Background worker that runs alongside FastAPI to receive updates via long-polling (getUpdates).
    """
    print("[Telegram Bot Poller] Background worker initialized.", flush=True)
    offset = 0
    commands_synced_token = None

    while True:
        try:
            conn = get_connection()
            token = get_telegram_bot_token(conn)
            conn.close()

            # Skip polling if token is empty or fake test token
            if not token or token == "123456:FAKE_TOKEN" or "FAKE" in token:
                await asyncio.sleep(5)
                continue

            # Ensure menu commands are synchronized to English on startup or token update
            if commands_synced_token != token:
                await sync_telegram_bot_commands(token)
                commands_synced_token = token

            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {"offset": offset, "timeout": 20, "allowed_updates": ["message", "callback_query"]}

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        updates = data.get("result", [])
                        for upd in updates:
                            upd_id = upd.get("update_id", 0)
                            if upd_id >= offset:
                                offset = upd_id + 1
                            print(f"[Telegram Bot] Received update #{upd_id}", flush=True)
                            asyncio.create_task(process_telegram_update(upd, token))
                elif resp.status_code == 409:
                    print(f"[Telegram Bot Poller] 409 Conflict: {resp.text}", flush=True)
                    await asyncio.sleep(5)
                else:
                    print(f"[Telegram Bot Poller] getUpdates status {resp.status_code}: {resp.text}", flush=True)
                    await asyncio.sleep(5)

        except asyncio.CancelledError:
            print("[Telegram Bot Poller] Polling Worker stopped.", flush=True)
            break
        except Exception as e:
            logger.warning(f"Telegram polling exception: {e}")
            await asyncio.sleep(10)
