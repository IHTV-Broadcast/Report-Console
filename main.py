"""
FastAPI Server & REST API for Quick Incident Reporter.
Supports:
- Passwordless Employee Portal (Name selection, fast 3-step reporting, My Reports)
- Salted & Hashed Admin Security (Session tokens, full CRUD, Telegram configuration)
- Real-time Telegram Dispatch with async worker and manual retry
- Seamless English UI with full bidirectional (LTR / RTL Farsi) support
"""

import os
import json
import sqlite3
import secrets
import string
import logging
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any, Literal

from fastapi import FastAPI, HTTPException, Header, Cookie, Response, Depends, Query, BackgroundTasks, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

from database import (
    get_connection, init_db, seed_initial_data_if_empty,
    hash_password, verify_password
)
from telegram_dispatcher import (
    get_telegram_bot_token, get_admin_telegram_id, get_telegram_config,
    format_private_incident_alert, format_telegram_alert,
    send_telegram_private_message, send_telegram_message
)
from telegram_bot import (
    process_telegram_update,
    telegram_polling_loop
)

logger = logging.getLogger("incident_portal")

# ----------------- APP INITIALIZATION -----------------
app = FastAPI(
    title="Quick Incident Reporter",
    description="Corporate Fast Incident Reporting System with Automated Telegram Dispatch",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Active Admin In-Memory Session Tokens: token -> { "created_at": iso_str }
ADMIN_SESSIONS: Dict[str, Dict[str, Any]] = {}

@app.on_event("startup")
async def startup_event():
    init_db(default_admin_password=os.getenv("ADMIN_PASSWORD", "admin123"))
    seed_initial_data_if_empty()
    # Launch background Telegram Bot polling loop if enabled
    if os.getenv("ENABLE_TELEGRAM_POLLING", "true").lower() in ("true", "1", "yes"):
        print("[FastAPI] Launching background Telegram Bot poller on @ihtv_report_bot...", flush=True)
        asyncio.create_task(telegram_polling_loop())

@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receives real-time updates from Telegram Webhook with deduplication."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    background_tasks.add_task(process_telegram_update, body)
    return {"ok": True}

@app.post("/api/telegram/simulate-update")
async def simulate_telegram_update(request: Request):
    """Direct update processing for automated integration tests."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    await process_telegram_update(body)
    return {"ok": True}

# ----------------- PYDANTIC SCHEMAS -----------------
class AdminLoginModel(BaseModel):
    password: str

class ReportCreateModel(BaseModel):
    reporter_name: str = Field(..., min_length=1)
    unit_id: int
    section_id: Optional[int] = None
    preset_tag: Optional[str] = None
    description: str = Field(..., min_length=2)
    priority: Literal["Critical", "Normal"] = "Normal"
    extra_mention_user_ids: Optional[List[int]] = []
    source: Optional[Literal["Web", "Telegram"]] = "Web"
    telegram_chat_id: Optional[str] = None
    telegram_update_id: Optional[int] = None

class ReportStatusUpdateModel(BaseModel):
    status: str
    resolution_notes: Optional[str] = ""
    resolved_by: Optional[str] = None

class UserModel(BaseModel):
    name: str
    role: Optional[str] = "Employee"
    telegram_id: Optional[str] = None
    telegram_username: Optional[str] = None
    is_active: Optional[bool] = True
    unit: Optional[str] = None
    work_hours: Optional[str] = None
    special_conditions: Optional[Any] = None
    work_location: Optional[str] = None
    position: Optional[str] = None
    managed_units: Optional[Any] = None

class UnitModel(BaseModel):
    name: str
    icon: Optional[str] = "layers"
    description: Optional[str] = ""
    sort_order: Optional[int] = 0
    is_active: Optional[bool] = True

class SectionModel(BaseModel):
    unit_id: int
    name: str
    description: Optional[str] = ""
    sort_order: Optional[int] = 0
    is_active: Optional[bool] = True
    manager_ids: Optional[List[int]] = []

class IssueCategoryModel(BaseModel):
    name: str
    unit_id: Optional[int] = None
    sort_order: Optional[int] = 0
    is_active: Optional[bool] = True

class TelegramSettingsModel(BaseModel):
    bot_token: str
    admin_telegram_id: Optional[str] = None
    chat_id: Optional[str] = None

class LinkTokenRequest(BaseModel):
    user_id: int

class VerifyLinkRequest(BaseModel):
    token: str
    telegram_id: str
    telegram_username: Optional[str] = None

class BulkDeleteModel(BaseModel):
    ids: List[int] = Field(..., min_items=1)

# ----------------- ADMIN SECURITY DEPENDENCY -----------------
def require_admin_auth(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None)
):
    token = x_admin_token or admin_session
    if not token or token not in ADMIN_SESSIONS:
        raise HTTPException(status_code=401, detail="Administrator session expired or invalid. Please login.")
    return ADMIN_SESSIONS[token]

# ----------------- DISPATCH BACKGROUND TASK -----------------
async def dispatch_report_to_telegram(report_id: int):
    """
    Dispatches private message notifications to Admin and selected staff.
    Ensures:
    1. Unconditional delivery to Admin.
    2. Delivery to each selected staff member.
    3. Idempotent retries (skips already SENT recipients).
    4. Per-recipient delivery tracking and error logging in dispatch_logs.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        rep_row = cursor.fetchone()
        if not rep_row:
            return

        report_dict = dict(rep_row)

        # Extra mentions
        cursor.execute("""
            SELECT u.id, u.name, u.telegram_id, u.telegram_username
            FROM report_mentions rm
            JOIN users u ON rm.user_id = u.id
            WHERE rm.report_id = ?
        """, (report_id,))
        mentions = [dict(r) for r in cursor.fetchall()]

        token = get_telegram_bot_token(conn)
        msg_text = format_private_incident_alert(report_dict, mentions)

        # Ensure dispatch_logs exist for this report. If empty, create them now.
        cursor.execute("SELECT COUNT(*) as cnt FROM dispatch_logs WHERE report_id = ?", (report_id,))
        cnt_row = cursor.fetchone()
        if not cnt_row or cnt_row["cnt"] == 0:
            now_iso = datetime.now().isoformat()
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

            # 2. Extra mentions (PV ONLY to selected staff, never to groups/channels)
            for m in mentions:
                if admin_user_id and m["id"] == admin_user_id:
                    continue
                if admin_tg_id and m.get("telegram_id") and str(m["telegram_id"]).strip() == str(admin_tg_id).strip():
                    continue
                cursor.execute("""
                    INSERT INTO dispatch_logs (report_id, recipient_role, user_id, user_name, telegram_id, status, attempted_at)
                    VALUES (?, 'MENTION', ?, ?, ?, 'PENDING', ?)
                """, (report_id, m["id"], m["name"], m.get("telegram_id"), now_iso))
            conn.commit()

        # Query pending or failed targets (NEVER resend to already SENT recipients)
        cursor.execute("""
            SELECT id, recipient_role, user_id, user_name, telegram_id, status
            FROM dispatch_logs
            WHERE report_id = ? AND status != 'SENT'
            ORDER BY id ASC
        """, (report_id,))
        pending_targets = [dict(r) for r in cursor.fetchall()]

        for target in pending_targets:
            log_id = target["id"]
            rec_role = target["recipient_role"]
            rec_uid = target.get("user_id")
            rec_name = target.get("user_name", "Staff")
            rec_tg_id = target.get("telegram_id")
            now_iso = datetime.now().isoformat()

            # Always sync with latest telegram_id from users table
            latest_tg_id = None
            if rec_role == "ADMIN":
                cursor.execute("SELECT telegram_id FROM users WHERE (role = 'Admin' OR name = 'RAL') AND is_active = 1 LIMIT 1")
                u_chk = cursor.fetchone()
                latest_tg_id = (u_chk["telegram_id"] if u_chk and u_chk["telegram_id"] else None) or "858324589"
            elif rec_uid:
                cursor.execute("SELECT telegram_id FROM users WHERE id = ?", (rec_uid,))
                u_chk = cursor.fetchone()
                if u_chk and u_chk["telegram_id"]:
                    latest_tg_id = str(u_chk["telegram_id"]).strip()

            if latest_tg_id:
                rec_tg_id = latest_tg_id
                cursor.execute("UPDATE dispatch_logs SET telegram_id = ? WHERE id = ?", (str(rec_tg_id).strip(), log_id))
                conn.commit()

            # Validation 1: Bot token configured
            if not token:
                cursor.execute("""
                    UPDATE dispatch_logs
                    SET status = 'FAILED', error_message = 'Telegram Bot Token is not configured in admin settings.', attempted_at = ?
                    WHERE id = ?
                """, (now_iso, log_id))
                conn.commit()
                continue

            # Validation 2: Missing recipient numeric Telegram ID
            if not rec_tg_id:
                err_label = "Group" if rec_role == "GROUP" else ("Admin (RAL)" if rec_role == "ADMIN" else f"User '{rec_name}'")
                err_msg = f"Telegram User ID is missing for {err_label}. Recipient must link their numeric Telegram User ID."
                cursor.execute("""
                    UPDATE dispatch_logs
                    SET status = 'FAILED', error_message = ?, attempted_at = ?
                    WHERE id = ?
                """, (err_msg, now_iso, log_id))
                conn.commit()
                continue

            # Send Private Telegram Message
            try:
                res = await send_telegram_private_message(token, str(rec_tg_id).strip(), msg_text)
                if res.get("ok"):
                    cursor.execute("""
                        UPDATE dispatch_logs
                        SET status = 'SENT', telegram_message_id = ?, error_message = NULL, attempted_at = ?
                        WHERE id = ?
                    """, (res.get("message_id"), now_iso, log_id))
                else:
                    cursor.execute("""
                        UPDATE dispatch_logs
                        SET status = 'FAILED', error_message = ?, attempted_at = ?
                        WHERE id = ?
                    """, (res.get("error", "Failed to send private Telegram alert"), now_iso, log_id))
            except Exception as send_err:
                cursor.execute("""
                    UPDATE dispatch_logs
                    SET status = 'FAILED', error_message = ?, attempted_at = ?
                    WHERE id = ?
                """, (str(send_err), now_iso, log_id))
            conn.commit()

    except Exception as e:
        logger.exception("Error during telegram dispatch background task")
    finally:
        conn.close()

# ----------------- PUBLIC / EMPLOYEE API -----------------

@app.get("/api/public/bootstrap")
def get_public_bootstrap():
    """Returns active users, units, sections, and issue presets for instant client boot."""
    conn = get_connection()
    cursor = conn.cursor()

    # Active Employees for fast 1-click name picker
    cursor.execute("""
        SELECT id, name, role, unit, work_hours, special_conditions, work_location, position, managed_units
        FROM users
        WHERE is_active = 1
        ORDER BY name ASC
    """)
    users = [dict(r) for r in cursor.fetchall()]

    # Active Units with their Sections
    cursor.execute("SELECT id, name, icon, description, sort_order FROM units WHERE is_active = 1 ORDER BY sort_order ASC, name ASC")
    units = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT id, unit_id, name, description, sort_order FROM sections WHERE is_active = 1 ORDER BY sort_order ASC, name ASC")
    all_sections = [dict(r) for r in cursor.fetchall()]

    # Nest sections inside their units
    sections_by_unit = {}
    for s in all_sections:
        u_id = s["unit_id"]
        if u_id not in sections_by_unit:
            sections_by_unit[u_id] = []
        sections_by_unit[u_id].append(s)

    for u in units:
        u["sections"] = sections_by_unit.get(u["id"], [])

    # Dynamic fast-pick issue preset tags from database
    cursor.execute("""
        SELECT id, name, unit_id, sort_order
        FROM issue_categories
        WHERE is_active = 1
        ORDER BY sort_order ASC, name ASC
    """)
    issue_categories = [dict(r) for r in cursor.fetchall()]
    preset_tags = [c["name"] for c in issue_categories]

    conn.close()
    return {
        "users": users,
        "units": units,
        "issue_categories": issue_categories,
        "preset_tags": preset_tags
    }

@app.post("/api/reports", status_code=status.HTTP_201_CREATED)
async def submit_incident_report(payload: ReportCreateModel, background_tasks: BackgroundTasks):
    """Submits a new incident report, commits to DB, records per-recipient dispatch targets, and enqueues Telegram dispatch."""
    conn = get_connection()
    cursor = conn.cursor()

    # Verify unit
    cursor.execute("SELECT name FROM units WHERE id = ? AND is_active = 1", (payload.unit_id,))
    u_row = cursor.fetchone()
    if not u_row:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or inactive Unit selected.")

    unit_name = u_row["name"]
    section_name = None

    if payload.section_id:
        cursor.execute("SELECT name FROM sections WHERE id = ? AND unit_id = ? AND is_active = 1", (payload.section_id, payload.unit_id))
        s_row = cursor.fetchone()
        if not s_row:
            conn.close()
            raise HTTPException(status_code=400, detail="Selected Section does not belong to the selected Unit.")
        section_name = s_row["name"]

    # Match reporter ID if exists
    cursor.execute("SELECT id FROM users WHERE name = ?", (payload.reporter_name.strip(),))
    rep_user = cursor.fetchone()
    reporter_id = rep_user["id"] if rep_user else None

    # Generate unique readable tracking code (e.g. INC-26-8492)
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

    cursor.execute("""
        INSERT INTO reports (
            tracking_code, reporter_name, reporter_id, unit_id, unit_name,
            section_id, section_name, preset_tag, description, priority,
            status, source, telegram_chat_id, telegram_update_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?, ?, ?, ?)
    """, (
        tracking_code, payload.reporter_name.strip(), reporter_id, payload.unit_id, unit_name,
        payload.section_id, section_name, payload.preset_tag, payload.description.strip(),
        payload.priority or "Normal", payload.source or "Web", payload.telegram_chat_id, payload.telegram_update_id,
        now_iso, now_iso
    ))
    report_id = cursor.lastrowid

    # Record extra mentions (Strictly Active Users Only)
    mentions_to_log = []
    if payload.extra_mention_user_ids:
        for uid in set(payload.extra_mention_user_ids):
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

    # 1. Insert Admin (RAL) PV Alert
    cursor.execute("""
        INSERT INTO dispatch_logs (report_id, recipient_role, user_id, user_name, telegram_id, status, attempted_at)
        VALUES (?, 'ADMIN', ?, ?, ?, 'PENDING', ?)
    """, (report_id, admin_user_id, admin_name, admin_tg_id, now_iso))

    # 2. Insert Mentions dispatch logs (PV ONLY to selected staff, never to groups/channels)
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

    # Enqueue Async Telegram Dispatcher
    background_tasks.add_task(dispatch_report_to_telegram, report_id)

    return {
        "success": True,
        "message": "Incident report registered successfully.",
        "report_id": report_id,
        "tracking_code": tracking_code
    }

@app.get("/api/reports/my")
def get_my_reports(reporter_name: str = Query(..., min_length=1)):
    """Returns historical reports registered by the specified employee name."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*,
               (SELECT status FROM dispatch_logs WHERE report_id = r.id ORDER BY id DESC LIMIT 1) as telegram_dispatch_status
        FROM reports r
        WHERE LOWER(TRIM(r.reporter_name)) = LOWER(TRIM(?))
        ORDER BY r.id DESC
    """, (reporter_name,))
    records = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return records

@app.get("/api/reports/{report_id}")
def get_report_detail(report_id: int):
    """Retrieves full details of a specific incident report."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    rep = cursor.fetchone()
    if not rep:
        conn.close()
        raise HTTPException(status_code=404, detail="Incident report not found.")

    report_dict = dict(rep)

    # Fetch assigned managers
    cursor.execute("""
        SELECT u.id, u.name, u.role, u.telegram_username
        FROM section_managers sm
        JOIN users u ON sm.user_id = u.id
        WHERE sm.section_id = ?
    """, (report_dict["section_id"],))
    managers = [dict(r) for r in cursor.fetchall()]

    # Fetch extra mentions
    cursor.execute("""
        SELECT u.id, u.name
        FROM report_mentions rm
        JOIN users u ON rm.user_id = u.id
        WHERE rm.report_id = ?
    """, (report_id,))
    mentions = [dict(r) for r in cursor.fetchall()]

    # Fetch dispatch logs with recipient breakdown
    cursor.execute("""
        SELECT id, recipient_role, user_id, user_name, telegram_id, status, telegram_message_id, error_message, attempted_at
        FROM dispatch_logs
        WHERE report_id = ?
        ORDER BY recipient_role ASC, id ASC
    """, (report_id,))
    logs = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "report": report_dict,
        "managers": managers,
        "extra_mentions": mentions,
        "dispatch_logs": logs
    }

# ----------------- ADMIN API -----------------

@app.post("/api/admin/login")
def admin_login(payload: AdminLoginModel, response: Response):
    """Validates admin master password against secure PBKDF2 hash."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'admin_password_hash'")
    h_row = cursor.fetchone()
    cursor.execute("SELECT value FROM settings WHERE key = 'admin_password_salt'")
    s_row = cursor.fetchone()
    conn.close()

    if not h_row or not s_row:
        raise HTTPException(status_code=500, detail="Admin password not configured in database.")

    if not verify_password(payload.password, s_row["value"], h_row["value"]):
        raise HTTPException(status_code=401, detail="Invalid administrator password.")

    # Generate secure session token
    token = "ADM-" + secrets.token_urlsafe(32)
    ADMIN_SESSIONS[token] = {
        "created_at": datetime.now().isoformat()
    }
    response.set_cookie(
        key="admin_session",
        value=token,
        httponly=False,
        samesite="lax",
        path="/"
    )
    return {
        "success": True,
        "token": token,
        "message": "Administrator authenticated successfully."
    }

@app.post("/api/admin/logout")
def admin_logout(
    response: Response,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None)
):
    """Revokes the admin session token and clears the session cookie."""
    token = x_admin_token or admin_session
    if token and token in ADMIN_SESSIONS:
        del ADMIN_SESSIONS[token]
    response.delete_cookie(key="admin_session", path="/")
    return {"success": True, "message": "Admin session revoked."}

@app.get("/api/admin/verify-session")
def admin_verify_session(admin_session: dict = Depends(require_admin_auth)):
    """Verifies that an active admin session is valid."""
    return {"valid": True}

@app.get("/api/admin/reports", dependencies=[Depends(require_admin_auth)])
def admin_list_reports(
    unit_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    priority_filter: Optional[str] = None,
    search: Optional[str] = None
):
    """Returns all incident reports with recipient PV delivery breakdown."""
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT r.*,
               (SELECT COUNT(*) FROM dispatch_logs WHERE report_id = r.id) as dispatch_total,
               (SELECT COUNT(*) FROM dispatch_logs WHERE report_id = r.id AND status = 'SENT') as dispatch_sent,
               (SELECT COUNT(*) FROM dispatch_logs WHERE report_id = r.id AND status = 'FAILED') as dispatch_failed,
               (SELECT COUNT(*) FROM dispatch_logs WHERE report_id = r.id AND status = 'PENDING') as dispatch_pending
        FROM reports r
        WHERE 1=1
    """
    params = []

    if unit_id:
        query += " AND r.unit_id = ?"
        params.append(unit_id)

    if status_filter:
        query += " AND r.status = ?"
        params.append(status_filter)

    if priority_filter:
        query += " AND r.priority = ?"
        params.append(priority_filter)

    if search:
        query += " AND (r.tracking_code LIKE ? OR r.description LIKE ? OR r.reporter_name LIKE ?)"
        s_wild = f"%{search.strip()}%"
        params.extend([s_wild, s_wild, s_wild])

    query += " ORDER BY r.id DESC"

    cursor.execute(query, tuple(params))
    raw_records = [dict(r) for r in cursor.fetchall()]
    conn.close()

    records = []
    for rec in raw_records:
        total = rec.get("dispatch_total", 0)
        sent = rec.get("dispatch_sent", 0)
        failed = rec.get("dispatch_failed", 0)
        pending = rec.get("dispatch_pending", 0)

        if total == 0:
            rec["telegram_dispatch_status"] = "UNSENT"
        elif sent == total:
            rec["telegram_dispatch_status"] = "SENT"
        elif failed > 0 and sent == 0:
            rec["telegram_dispatch_status"] = "FAILED"
        elif failed > 0 and sent > 0:
            rec["telegram_dispatch_status"] = "PARTIAL"
        elif pending > 0:
            rec["telegram_dispatch_status"] = "PENDING"
        else:
            rec["telegram_dispatch_status"] = "PENDING"

        records.append(rec)

    return records

@app.patch("/api/admin/reports/{report_id}/status", dependencies=[Depends(require_admin_auth)])
def admin_update_report_status(report_id: int, payload: ReportStatusUpdateModel):
    """Updates status and resolution notes of an incident."""
    conn = get_connection()
    cursor = conn.cursor()

    now_iso = datetime.now().isoformat()
    cursor.execute("""
        UPDATE reports
        SET status = ?,
            resolution_notes = ?,
            resolved_by = ?,
            resolved_at = CASE WHEN ? IN ('Resolved', 'Closed') THEN ? ELSE resolved_at END,
            updated_at = ?
        WHERE id = ?
    """, (
        payload.status,
        payload.resolution_notes or "",
        payload.resolved_by or "Administrator",
        payload.status,
        now_iso,
        now_iso,
        report_id
    ))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Incident report not found.")

    conn.commit()
    conn.close()
    return {"success": True, "message": f"Report status changed to {payload.status}"}

@app.post("/api/admin/reports/{report_id}/retry-dispatch", dependencies=[Depends(require_admin_auth)])
async def admin_retry_telegram_dispatch(report_id: int, background_tasks: BackgroundTasks):
    """Manually re-enqueues Telegram alert for an incident, skipping already SENT recipients."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM reports WHERE id = ?", (report_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Incident report not found.")

    cursor.execute("SELECT status FROM dispatch_logs WHERE report_id = ?", (report_id,))
    existing_logs = cursor.fetchall()
    conn.close()

    if existing_logs and all(r["status"] == "SENT" for r in existing_logs):
        return {
            "success": True,
            "message": "All recipients have already received the notification successfully. No retry needed.",
            "skipped": True
        }

    background_tasks.add_task(dispatch_report_to_telegram, report_id)
    return {"success": True, "message": "Telegram private dispatch re-enqueued for pending/failed recipients."}

@app.delete("/api/admin/reports/{report_id}", dependencies=[Depends(require_admin_auth)])
def admin_delete_single_report(report_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tracking_code FROM reports WHERE id = ?", (report_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Incident report not found.")
    cursor.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    conn.close()
    return {"success": True, "deleted": True, "message": f"Report #{row['tracking_code']} permanently deleted."}

@app.post("/api/admin/reports/bulk-delete", dependencies=[Depends(require_admin_auth)])
def admin_bulk_delete_reports(payload: BulkDeleteModel):
    if not payload.ids:
        return {"success": True, "deleted": 0, "message": "No reports selected."}
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in payload.ids)
    cursor.execute(f"DELETE FROM reports WHERE id IN ({placeholders})", payload.ids)
    cnt = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": True, "deleted": cnt, "message": f"{cnt} incident report(s) deleted successfully."}



# --- Organizational CRUD (Units & Sections) ---

@app.get("/api/admin/units-sections", dependencies=[Depends(require_admin_auth)])
def admin_get_units_and_sections():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT u.*,
               (SELECT COUNT(*) FROM reports WHERE unit_id = u.id) as report_count
        FROM units u
        ORDER BY u.sort_order ASC, u.name ASC
    """)
    units = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT s.*,
               GROUP_CONCAT(sm.user_id) as manager_ids_str,
               (SELECT COUNT(*) FROM reports WHERE section_id = s.id) as report_count
        FROM sections s
        LEFT JOIN section_managers sm ON s.id = sm.section_id
        GROUP BY s.id
        ORDER BY s.sort_order ASC, s.name ASC
    """)
    sections = []
    for r in cursor.fetchall():
        s_dict = dict(r)
        m_str = s_dict.pop("manager_ids_str", None)
        s_dict["manager_ids"] = [int(x) for x in m_str.split(",")] if m_str else []
        sections.append(s_dict)

    conn.close()
    return {"units": units, "sections": sections}

@app.post("/api/admin/units", dependencies=[Depends(require_admin_auth)])
def admin_create_unit(payload: UnitModel):
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    try:
        cursor.execute("""
            INSERT INTO units (name, icon, description, sort_order, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            payload.name.strip(),
            payload.icon or "layers",
            payload.description or "",
            payload.sort_order or 0,
            1 if payload.is_active else 0,
            now_iso
        ))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return {"success": True, "id": new_id, "message": f"Unit '{payload.name}' created."}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="A Unit with this name already exists.")

@app.put("/api/admin/units/{unit_id}", dependencies=[Depends(require_admin_auth)])
def admin_update_unit(unit_id: int, payload: UnitModel):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE units
            SET name = ?, icon = ?, description = ?, sort_order = ?, is_active = ?
            WHERE id = ?
        """, (
            payload.name.strip(),
            payload.icon or "layers",
            payload.description or "",
            payload.sort_order or 0,
            1 if payload.is_active else 0,
            unit_id
        ))
        conn.commit()
        conn.close()
        return {"success": True, "message": f"Unit '{payload.name}' updated."}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Another Unit with this name already exists.")

@app.patch("/api/admin/units/{unit_id}/toggle-active", dependencies=[Depends(require_admin_auth)])
def admin_toggle_unit_active(unit_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_active, name FROM units WHERE id = ?", (unit_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Unit not found.")
    new_active = 0 if row["is_active"] else 1
    cursor.execute("UPDATE units SET is_active = ? WHERE id = ?", (new_active, unit_id))
    conn.commit()
    conn.close()
    status_str = "activated" if new_active else "deactivated"
    return {"success": True, "is_active": bool(new_active), "message": f"Unit '{row['name']}' {status_str}."}

@app.delete("/api/admin/units/{unit_id}", dependencies=[Depends(require_admin_auth)])
def admin_delete_unit(unit_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM units WHERE id = ?", (unit_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Unit not found.")
    unit_name = row["name"]
    cursor.execute("SELECT COUNT(*) as cnt FROM reports WHERE unit_id = ?", (unit_id,))
    rep_cnt = cursor.fetchone()["cnt"]
    if rep_cnt > 0:
        cursor.execute("UPDATE units SET is_active = 0 WHERE id = ?", (unit_id,))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "deactivated": True,
            "message": f"Unit '{unit_name}' has {rep_cnt} historical reports. It was deactivated to protect historical records."
        }
    cursor.execute("DELETE FROM units WHERE id = ?", (unit_id,))
    conn.commit()
    conn.close()
    return {"success": True, "deleted": True, "message": f"Unit '{unit_name}' permanently deleted."}

@app.post("/api/admin/units/bulk-delete", dependencies=[Depends(require_admin_auth)])
def admin_bulk_delete_units(payload: BulkDeleteModel):
    if not payload.ids:
        return {"success": True, "deleted": 0, "deactivated": 0, "message": "No units selected."}
    conn = get_connection()
    cursor = conn.cursor()
    deleted_cnt = 0
    deactivated_cnt = 0
    for uid in payload.ids:
        cursor.execute("SELECT COUNT(*) as cnt FROM reports WHERE unit_id = ?", (uid,))
        rep_cnt = cursor.fetchone()["cnt"]
        if rep_cnt > 0:
            cursor.execute("UPDATE units SET is_active = 0 WHERE id = ?", (uid,))
            deactivated_cnt += 1
        else:
            cursor.execute("DELETE FROM sections WHERE unit_id = ?", (uid,))
            cursor.execute("DELETE FROM units WHERE id = ?", (uid,))
            deleted_cnt += 1
    conn.commit()
    conn.close()
    msg = f"Processed {deleted_cnt + deactivated_cnt} unit(s): {deleted_cnt} deleted, {deactivated_cnt} deactivated to protect reports."
    return {"success": True, "deleted": deleted_cnt, "deactivated": deactivated_cnt, "message": msg}

@app.post("/api/admin/sections", dependencies=[Depends(require_admin_auth)])
def admin_create_section(payload: SectionModel):
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    try:
        cursor.execute("""
            INSERT INTO sections (unit_id, name, description, sort_order, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            payload.unit_id,
            payload.name.strip(),
            payload.description or "",
            payload.sort_order or 0,
            1 if payload.is_active else 0,
            now_iso
        ))
        sec_id = cursor.lastrowid

        if payload.manager_ids:
            for uid in payload.manager_ids:
                cursor.execute("""
                    INSERT OR IGNORE INTO section_managers (section_id, user_id)
                    VALUES (?, ?)
                """, (sec_id, uid))

        conn.commit()
        conn.close()
        return {"success": True, "id": sec_id, "message": "Section created."}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="This Section already exists inside the selected Unit.")

@app.put("/api/admin/sections/{section_id}", dependencies=[Depends(require_admin_auth)])
def admin_update_section(section_id: int, payload: SectionModel):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE sections
            SET unit_id = ?, name = ?, description = ?, sort_order = ?, is_active = ?
            WHERE id = ?
        """, (
            payload.unit_id,
            payload.name.strip(),
            payload.description or "",
            payload.sort_order or 0,
            1 if payload.is_active else 0,
            section_id
        ))

        cursor.execute("DELETE FROM section_managers WHERE section_id = ?", (section_id,))
        if payload.manager_ids:
            for uid in payload.manager_ids:
                cursor.execute("""
                    INSERT OR IGNORE INTO section_managers (section_id, user_id)
                    VALUES (?, ?)
                """, (section_id, uid))

        conn.commit()
        conn.close()
        return {"success": True, "message": "Section updated."}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Section update conflict.")

@app.patch("/api/admin/sections/{section_id}/toggle-active", dependencies=[Depends(require_admin_auth)])
def admin_toggle_section_active(section_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_active, name FROM sections WHERE id = ?", (section_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Section not found.")
    new_active = 0 if row["is_active"] else 1
    cursor.execute("UPDATE sections SET is_active = ? WHERE id = ?", (new_active, section_id))
    conn.commit()
    conn.close()
    status_str = "activated" if new_active else "deactivated"
    return {"success": True, "is_active": bool(new_active), "message": f"Section '{row['name']}' {status_str}."}

@app.delete("/api/admin/sections/{section_id}", dependencies=[Depends(require_admin_auth)])
def admin_delete_section(section_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sections WHERE id = ?", (section_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Section not found.")
    sec_name = row["name"]
    cursor.execute("SELECT COUNT(*) as cnt FROM reports WHERE section_id = ?", (section_id,))
    rep_cnt = cursor.fetchone()["cnt"]
    if rep_cnt > 0:
        cursor.execute("UPDATE sections SET is_active = 0 WHERE id = ?", (section_id,))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "deactivated": True,
            "message": f"Section '{sec_name}' has {rep_cnt} historical reports. It was deactivated to protect historical records."
        }
    cursor.execute("DELETE FROM sections WHERE id = ?", (section_id,))
    conn.commit()
    conn.close()
    return {"success": True, "deleted": True, "message": f"Section '{sec_name}' permanently deleted."}

@app.post("/api/admin/sections/bulk-delete", dependencies=[Depends(require_admin_auth)])
def admin_bulk_delete_sections(payload: BulkDeleteModel):
    if not payload.ids:
        return {"success": True, "deleted": 0, "deactivated": 0, "message": "No sections selected."}
    conn = get_connection()
    cursor = conn.cursor()
    deleted_cnt = 0
    deactivated_cnt = 0
    for sid in payload.ids:
        cursor.execute("SELECT COUNT(*) as cnt FROM reports WHERE section_id = ?", (sid,))
        rep_cnt = cursor.fetchone()["cnt"]
        if rep_cnt > 0:
            cursor.execute("UPDATE sections SET is_active = 0 WHERE id = ?", (sid,))
            deactivated_cnt += 1
        else:
            cursor.execute("DELETE FROM sections WHERE id = ?", (sid,))
            deleted_cnt += 1
    conn.commit()
    conn.close()
    msg = f"Processed {deleted_cnt + deactivated_cnt} section(s): {deleted_cnt} deleted, {deactivated_cnt} deactivated."
    return {"success": True, "deleted": deleted_cnt, "deactivated": deactivated_cnt, "message": msg}

# --- Users & Personnel Management ---

@app.get("/api/admin/users", dependencies=[Depends(require_admin_auth)])
def admin_get_users(status_filter: Optional[str] = "all"):
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT u.*,
               (SELECT COUNT(*) FROM reports WHERE reporter_id = u.id) as report_count
        FROM users u
        WHERE 1=1
    """
    if status_filter == "active":
        query += " AND u.is_active = 1"
    elif status_filter == "inactive":
        query += " AND u.is_active = 0"
    elif status_filter == "missing_tg":
        query += " AND (u.telegram_id IS NULL OR TRIM(u.telegram_id) = '')"

    query += " ORDER BY (u.role = 'Admin') DESC, u.is_active DESC, u.name ASC"
    cursor.execute(query)
    users = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return users

def validate_telegram_id(tg_id: Optional[Any], required: bool = True) -> Optional[str]:
    """
    Validates that Telegram User ID is a valid positive numeric account ID (digits only).
    Rejects @usernames, non-numeric strings, and empty values when required.
    """
    if tg_id is None:
        if required:
            raise HTTPException(
                status_code=422,
                detail="Telegram User ID is required when adding a new employee."
            )
        return None

    raw_val = str(tg_id).strip()
    if not raw_val:
        if required:
            raise HTTPException(
                status_code=422,
                detail="Telegram User ID is required when adding a new employee."
            )
        return None

    if raw_val.startswith("@"):
        raise HTTPException(
            status_code=422,
            detail="Invalid Telegram User ID: You entered a username ('@...'). Telegram User ID must be a numeric account ID (digits only, e.g. 123456789). Usernames are not allowed."
        )

    if not raw_val.isdigit():
        raise HTTPException(
            status_code=422,
            detail="Invalid Telegram User ID: Must contain digits only (e.g. 123456789). Letters, symbols, and usernames are not allowed."
        )

    if len(raw_val) < 5 or len(raw_val) > 20:
        raise HTTPException(
            status_code=422,
            detail="Invalid Telegram User ID: Telegram account IDs typically contain between 5 and 20 digits."
        )

    return raw_val

def check_duplicate_telegram_id(conn, tg_id: str, exclude_user_id: Optional[int] = None, payload_role: Optional[str] = "Employee"):
    """
    Ensures that a Telegram User ID is not assigned to another active employee.
    Allows Admin accounts to share master administrative telegram ID if applicable.
    """
    if not tg_id:
        return
    cursor = conn.cursor()
    if exclude_user_id:
        cursor.execute("""
            SELECT id, name, role FROM users 
            WHERE telegram_id = ? AND id != ? AND is_active = 1
        """, (tg_id, exclude_user_id))
    else:
        cursor.execute("""
            SELECT id, name, role FROM users 
            WHERE telegram_id = ? AND is_active = 1
        """, (tg_id,))
    
    existing = cursor.fetchone()
    if existing:
        if existing["role"] == "Admin" and payload_role == "Admin":
            return
        raise HTTPException(
            status_code=400,
            detail=f"Telegram User ID '{tg_id}' is already registered for employee '{existing['name']}'. Each employee must have a unique Telegram User ID."
        )

@app.post("/api/admin/users", dependencies=[Depends(require_admin_auth)])
def admin_create_user(payload: UserModel):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Employee Name is required.")

    conn = get_connection()
    # Telegram User ID is strictly required when creating a new employee
    tg_id = validate_telegram_id(payload.telegram_id, required=True)
    check_duplicate_telegram_id(conn, tg_id, exclude_user_id=None, payload_role=payload.role)

    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    spec_str = json.dumps(payload.special_conditions) if isinstance(payload.special_conditions, list) else (payload.special_conditions or None)
    managed_str = json.dumps(payload.managed_units) if isinstance(payload.managed_units, list) else (payload.managed_units or None)
    try:
        cursor.execute("""
            INSERT INTO users (
                name, role, telegram_id, telegram_username, is_active,
                unit, work_hours, special_conditions, work_location, position, managed_units,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            payload.role or "Employee",
            tg_id,
            None,
            1 if payload.is_active else 0,
            payload.unit.strip() if payload.unit else None,
            payload.work_hours.strip() if payload.work_hours else None,
            spec_str,
            payload.work_location.strip() if payload.work_location else None,
            payload.position.strip() if payload.position else None,
            managed_str,
            now_iso
        ))
        conn.commit()
        uid = cursor.lastrowid
        conn.close()
        return {"success": True, "id": uid, "message": f"Staff member '{name}' added successfully."}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Employee with this name already exists.")

@app.put("/api/admin/users/{user_id}", dependencies=[Depends(require_admin_auth)])
def admin_update_user(user_id: int, payload: UserModel):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Employee Name is required.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, telegram_id FROM users WHERE id = ?", (user_id,))
    target_user = cursor.fetchone()
    if not target_user:
        conn.close()
        raise HTTPException(status_code=404, detail="Employee not found.")

    # Validate Telegram User ID if provided
    tg_id = validate_telegram_id(payload.telegram_id, required=False)
    if tg_id:
        check_duplicate_telegram_id(conn, tg_id, exclude_user_id=user_id, payload_role=payload.role)

    spec_str = json.dumps(payload.special_conditions) if isinstance(payload.special_conditions, list) else (payload.special_conditions or None)
    managed_str = json.dumps(payload.managed_units) if isinstance(payload.managed_units, list) else (payload.managed_units or None)
    try:
        cursor.execute("""
            UPDATE users
            SET name = ?,
                role = ?,
                telegram_id = ?,
                telegram_username = ?,
                is_active = ?,
                unit = ?,
                work_hours = ?,
                special_conditions = ?,
                work_location = ?,
                position = ?,
                managed_units = ?
            WHERE id = ?
        """, (
            name,
            payload.role or "Employee",
            tg_id,
            None,
            1 if payload.is_active else 0,
            payload.unit.strip() if payload.unit else None,
            payload.work_hours.strip() if payload.work_hours else None,
            spec_str,
            payload.work_location.strip() if payload.work_location else None,
            payload.position.strip() if payload.position else None,
            managed_str,
            user_id
        ))
        conn.commit()
        conn.close()
        return {"success": True, "message": f"Employee '{name}' updated successfully."}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Another employee with this name already exists.")

@app.patch("/api/admin/users/{user_id}/toggle-active", dependencies=[Depends(require_admin_auth)])
def admin_toggle_user_active(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_active, name FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")
    new_active = 0 if row["is_active"] else 1
    cursor.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_active, user_id))
    conn.commit()
    conn.close()
    status_str = "activated" if new_active else "deactivated"
    return {"success": True, "is_active": bool(new_active), "message": f"Staff member '{row['name']}' {status_str}."}

@app.delete("/api/admin/users/{user_id}", dependencies=[Depends(require_admin_auth)])
def admin_delete_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")
    user_name = row["name"]
    cursor.execute("SELECT COUNT(*) as cnt FROM reports WHERE reporter_id = ?", (user_id,))
    rep_cnt = cursor.fetchone()["cnt"]
    if rep_cnt > 0:
        cursor.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "deactivated": True,
            "message": f"User '{user_name}' has {rep_cnt} historical reports. The user was deactivated instead of deleted to protect historical records."
        }
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"success": True, "deleted": True, "message": f"User '{user_name}' permanently deleted."}

@app.post("/api/admin/users/bulk-delete", dependencies=[Depends(require_admin_auth)])
def admin_bulk_delete_users(payload: BulkDeleteModel):
    if not payload.ids:
        return {"success": True, "deleted": 0, "deactivated": 0, "message": "No employees selected."}
    conn = get_connection()
    cursor = conn.cursor()
    deleted_cnt = 0
    deactivated_cnt = 0
    for uid in payload.ids:
        cursor.execute("SELECT name, role FROM users WHERE id = ?", (uid,))
        u = cursor.fetchone()
        if not u or (u["name"] == "Admin" and u["role"] == "Admin"):
            continue
        cursor.execute("SELECT COUNT(*) as cnt FROM reports WHERE reporter_id = ?", (uid,))
        rep_cnt = cursor.fetchone()["cnt"]
        if rep_cnt > 0:
            cursor.execute("UPDATE users SET is_active = 0 WHERE id = ?", (uid,))
            deactivated_cnt += 1
        else:
            cursor.execute("DELETE FROM users WHERE id = ?", (uid,))
            deleted_cnt += 1
    conn.commit()
    conn.close()
    msg = f"Processed {deleted_cnt + deactivated_cnt} employee(s): {deleted_cnt} deleted, {deactivated_cnt} deactivated to protect reports."
    return {"success": True, "deleted": deleted_cnt, "deactivated": deactivated_cnt, "message": msg}

# --- Issue Categories / Presets Management ---

@app.get("/api/admin/issue-categories", dependencies=[Depends(require_admin_auth)])
def admin_get_issue_categories(status_filter: Optional[str] = "all"):
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT c.*, u.name as unit_name,
               (SELECT COUNT(*) FROM reports WHERE preset_tag = c.name) as report_count
        FROM issue_categories c
        LEFT JOIN units u ON c.unit_id = u.id
        WHERE 1=1
    """
    if status_filter == "active":
        query += " AND c.is_active = 1"
    elif status_filter == "inactive":
        query += " AND c.is_active = 0"

    query += " ORDER BY c.sort_order ASC, c.name ASC"
    cursor.execute(query)
    categories = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return categories

@app.post("/api/admin/issue-categories", dependencies=[Depends(require_admin_auth)])
def admin_create_issue_category(payload: IssueCategoryModel):
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    unit_id_val = payload.unit_id if (payload.unit_id and payload.unit_id > 0) else None
    try:
        cursor.execute("""
            INSERT INTO issue_categories (name, unit_id, sort_order, is_active, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            payload.name.strip(),
            unit_id_val,
            payload.sort_order or 0,
            1 if payload.is_active else 0,
            now_iso
        ))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return {"success": True, "id": new_id, "message": f"Issue option '{payload.name}' created."}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="An issue option with this name already exists in this scope.")

@app.put("/api/admin/issue-categories/{category_id}", dependencies=[Depends(require_admin_auth)])
def admin_update_issue_category(category_id: int, payload: IssueCategoryModel):
    conn = get_connection()
    cursor = conn.cursor()
    unit_id_val = payload.unit_id if (payload.unit_id and payload.unit_id > 0) else None
    try:
        cursor.execute("""
            UPDATE issue_categories
            SET name = ?,
                unit_id = ?,
                sort_order = ?,
                is_active = ?
            WHERE id = ?
        """, (
            payload.name.strip(),
            unit_id_val,
            payload.sort_order or 0,
            1 if payload.is_active else 0,
            category_id
        ))
        conn.commit()
        conn.close()
        return {"success": True, "message": f"Issue option '{payload.name}' updated."}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Another issue option with this name already exists in this scope.")

@app.patch("/api/admin/issue-categories/{category_id}/toggle-active", dependencies=[Depends(require_admin_auth)])
def admin_toggle_issue_category_active(category_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_active, name FROM issue_categories WHERE id = ?", (category_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Issue option not found.")
    new_active = 0 if row["is_active"] else 1
    cursor.execute("UPDATE issue_categories SET is_active = ? WHERE id = ?", (new_active, category_id))
    conn.commit()
    conn.close()
    status_str = "activated" if new_active else "deactivated"
    return {"success": True, "is_active": bool(new_active), "message": f"Option '{row['name']}' {status_str}."}

@app.delete("/api/admin/issue-categories/{category_id}", dependencies=[Depends(require_admin_auth)])
def admin_delete_issue_category(category_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM issue_categories WHERE id = ?", (category_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Issue option not found.")
    cat_name = row["name"]
    cursor.execute("SELECT COUNT(*) as cnt FROM reports WHERE preset_tag = ?", (cat_name,))
    rep_cnt = cursor.fetchone()["cnt"]
    if rep_cnt > 0:
        cursor.execute("UPDATE issue_categories SET is_active = 0 WHERE id = ?", (category_id,))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "deactivated": True,
            "message": f"Option '{cat_name}' is referenced in {rep_cnt} historical reports. It was deactivated to preserve report history."
        }
    cursor.execute("DELETE FROM issue_categories WHERE id = ?", (category_id,))
    conn.commit()
    conn.close()
    return {"success": True, "deleted": True, "message": f"Option '{cat_name}' permanently deleted."}

@app.post("/api/admin/issue-categories/bulk-delete", dependencies=[Depends(require_admin_auth)])
def admin_bulk_delete_issue_categories(payload: BulkDeleteModel):
    if not payload.ids:
        return {"success": True, "deleted": 0, "message": "No categories selected."}
    conn = get_connection()
    cursor = conn.cursor()
    deleted_cnt = 0
    deactivated_cnt = 0
    for cid in payload.ids:
        cursor.execute("SELECT name FROM issue_categories WHERE id = ?", (cid,))
        c = cursor.fetchone()
        if not c:
            continue
        cursor.execute("SELECT COUNT(*) as cnt FROM reports WHERE preset_tag = ?", (c["name"],))
        rep_cnt = cursor.fetchone()["cnt"]
        if rep_cnt > 0:
            cursor.execute("UPDATE issue_categories SET is_active = 0 WHERE id = ?", (cid,))
            deactivated_cnt += 1
        else:
            cursor.execute("DELETE FROM issue_categories WHERE id = ?", (cid,))
            deleted_cnt += 1
    conn.commit()
    conn.close()
    msg = f"Processed {deleted_cnt + deactivated_cnt} category option(s): {deleted_cnt} deleted, {deactivated_cnt} deactivated to preserve history."
    return {"success": True, "deleted": deleted_cnt, "deactivated": deactivated_cnt, "message": msg}


# --- Telegram Settings & PV Test Endpoint ---

@app.get("/api/admin/telegram", dependencies=[Depends(require_admin_auth)])
def admin_get_telegram_settings():
    conn = get_connection()
    token = get_telegram_bot_token(conn)
    admin_tg_id = get_admin_telegram_id(conn)
    conn.close()
    masked_token = f"{token[:8]}...{token[-4:]}" if len(token) > 15 else token
    return {
        "bot_token": masked_token,
        "is_configured": bool(token and admin_tg_id),
        "admin_telegram_id": admin_tg_id or "",
        "chat_id": admin_tg_id or "" # backwards compatibility alias
    }

@app.post("/api/admin/telegram", dependencies=[Depends(require_admin_auth)])
def admin_save_telegram_settings(payload: TelegramSettingsModel):
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()

    tg_id = (payload.admin_telegram_id or payload.chat_id or "").strip()
    new_token = payload.bot_token.strip()

    # Do not overwrite with masked token if user did not re-type token
    if "..." not in new_token and new_token:
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES ('telegram_bot_token', ?, ?)
        """, (new_token, now_iso))

    cursor.execute("""
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES ('admin_telegram_id', ?, ?)
    """, (tg_id, now_iso))

    # Keep telegram_chat_id synced for backwards compatibility
    cursor.execute("""
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES ('telegram_chat_id', ?, ?)
    """, (tg_id, now_iso))

    if tg_id.startswith("@") or tg_id.startswith("-100"):
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES ('telegram_group_id', ?, ?)
        """, (tg_id, now_iso))

    # If an Admin user exists in users table and tg_id is numeric PV, update their telegram_id
    if tg_id and not tg_id.startswith("@") and not tg_id.startswith("-"):
        cursor.execute("UPDATE users SET telegram_id = ? WHERE role = 'Admin'", (tg_id,))

    conn.commit()
    conn.close()
    return {"success": True, "message": "Telegram settings saved."}

@app.post("/api/admin/telegram/test", dependencies=[Depends(require_admin_auth)])
async def admin_test_telegram_connection():
    """Sends a direct message test alert directly to configured Telegram Group or Admin chat."""
    conn = get_connection()
    token = get_telegram_bot_token(conn)
    admin_tg_id = get_admin_telegram_id(conn)
    conn.close()

    if not token:
        raise HTTPException(status_code=400, detail="Telegram Bot Token must be configured first.")
    if not admin_tg_id:
        raise HTTPException(
            status_code=400,
            detail="Telegram Chat / Group ID is not configured. Please enter the target Group ID or Admin ID."
        )

    is_group = str(admin_tg_id).startswith("-") or str(admin_tg_id).startswith("@")
    dest_label = f"Group <code>{admin_tg_id}</code>" if is_group else f"Admin <code>{admin_tg_id}</code>"

    test_msg = (
        "🤖 <b>QUICK INCIDENT DISPATCHER: CONNECTION TEST</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ The Incident Reporting Portal successfully verified Telegram delivery to {dest_label}.\n"
        f"🎯 <b>Target:</b> <code>{admin_tg_id}</code>\n"
        f"🕒 <b>Timestamp:</b> <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
    )
    res = await send_telegram_private_message(token, str(admin_tg_id), test_msg)
    if not res.get("ok"):
        raise HTTPException(status_code=502, detail=res.get("error", "Failed to send test message."))

    return {"success": True, "message": f"Test alert delivered to Telegram target ({admin_tg_id}) successfully!"}

# --- Telegram Account Linking for Staff ---

@app.post("/api/telegram/generate-link-token")
def generate_telegram_link_token(payload: LinkTokenRequest):
    """Generates a secure 8-character linking token for a user to link their Telegram account."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, telegram_id FROM users WHERE id = ?", (payload.user_id,))
    u_row = cursor.fetchone()
    if not u_row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")

    token = secrets.token_hex(4).upper()
    now_iso = datetime.now().isoformat()
    cursor.execute("DELETE FROM telegram_link_tokens WHERE user_id = ?", (payload.user_id,))
    cursor.execute("""
        INSERT INTO telegram_link_tokens (token, user_id, expires_at, created_at)
        VALUES (?, ?, datetime('now', '+1 day'), ?)
    """, (token, payload.user_id, now_iso))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "token": token,
        "user_id": payload.user_id,
        "user_name": u_row["name"],
        "instructions": f"Send this code to the bot: /start link_{token}"
    }

@app.post("/api/telegram/verify-link")
def verify_telegram_link(payload: VerifyLinkRequest):
    """Validates linking token and associates Telegram User ID to the employee profile."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id FROM telegram_link_tokens
        WHERE token = ? AND expires_at > datetime('now')
    """, (payload.token.strip().upper(),))
    t_row = cursor.fetchone()
    if not t_row:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or expired linking token.")

    uid = t_row["user_id"]
    cursor.execute("""
        UPDATE users
        SET telegram_id = ?, telegram_username = ?
        WHERE id = ?
    """, (payload.telegram_id.strip(), payload.telegram_username.strip() if payload.telegram_username else None, uid))
    cursor.execute("DELETE FROM telegram_link_tokens WHERE token = ?", (payload.token.strip().upper(),))
    conn.commit()

    cursor.execute("SELECT id, name, role, telegram_id, telegram_username FROM users WHERE id = ?", (uid,))
    updated_user = dict(cursor.fetchone())
    conn.close()

    return {
        "success": True,
        "message": f"Telegram account linked successfully to {updated_user['name']}.",
        "user": updated_user
    }

@app.get("/api/telegram/user-status")
def get_user_telegram_status(user_id: int = Query(...)):
    """Checks whether a user has a linked Telegram ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, telegram_id, telegram_username FROM users WHERE id = ?", (user_id,))
    u = cursor.fetchone()
    conn.close()
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    is_linked = bool(u["telegram_id"])
    return {
        "user_id": u["id"],
        "name": u["name"],
        "is_linked": is_linked,
        "telegram_id": u["telegram_id"] if is_linked else None,
        "telegram_username": u["telegram_username"]
    }

# ----------------- STATIC ASSETS ROUTING -----------------
# Serves single-page application frontend
@app.get("/")
def serve_home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/admin")
@app.get("/admin/")
def serve_admin(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
    accept: Optional[str] = Header(None)
):
    # Strictly disallow direct browsing to admin panel without valid session token
    token = x_admin_token or admin_session
    if not token or token not in ADMIN_SESSIONS:
        if accept and "text/html" in accept:
            html_content = """<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Authentication Required</title>
    <style>
        body { background: #0b0f17; color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 16px; box-sizing: border-box; }
        .card { background: #131b2e; border: 1px solid #1e293b; border-radius: 16px; padding: 36px 28px; max-width: 460px; width: 100%; text-align: center; box-shadow: 0 20px 40px rgba(0,0,0,0.6); }
        .icon-wrap { width: 64px; height: 64px; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 32px; margin: 0 auto 18px; }
        h1 { margin: 0 0 10px; font-size: 20px; font-weight: 700; color: #f8fafc; }
        p { margin: 0 0 24px; color: #94a3b8; font-size: 14px; line-height: 1.6; }
        .code-box { background: rgba(255,255,255,0.04); border: 1px dashed rgba(245, 158, 11, 0.3); border-radius: 8px; padding: 10px; margin-bottom: 24px; font-size: 13px; color: #f59e0b; }
        .btn-primary { display: block; width: 100%; background: #6366f1; color: #fff; text-decoration: none; padding: 13px 20px; border-radius: 10px; font-weight: 600; font-size: 15px; box-sizing: border-box; transition: 0.2s; }
        .btn-primary:hover { background: #4f46e5; }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon-wrap">🛡️</div>
        <h1>Administrator Authentication Required</h1>
        <p>For security reasons, direct access via the browser address bar is restricted.<br>Please open the sign-in modal and enter your admin password.</p>
        <div class="code-box">Default Password: <strong>admin123</strong></div>
        <a href="/?open_admin=1" class="btn-primary">Open Admin Sign-In Form</a>
    </div>
</body>
</html>"""
            return HTMLResponse(content=html_content, status_code=status.HTTP_401_UNAUTHORIZED)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access Denied: Admin session token required. Please authenticate via the Employee Portal login."
        )
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))

@app.get("/reports/{report_id}")
def serve_report_view(report_id: int):
    return FileResponse(os.path.join(STATIC_DIR, "report_detail.html"))

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3006))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=True)
