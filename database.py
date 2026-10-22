"""
Database initialization and models for Quick Incident Reporter.
Uses SQLite with WAL mode for fast, concurrent, and reliable local operations.
"""

import os
import json
import sqlite3
import hashlib
import secrets
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "incidents.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def hash_password(password: str, salt: Optional[str] = None) -> tuple:
    """PBKDF2-HMAC-SHA256 password hashing with unique salt."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100_000
    ).hex()
    return hashed, salt

def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    hashed, _ = hash_password(password, salt)
    return secrets.compare_digest(hashed, expected_hash)

def init_db(default_admin_password: str = "admin123"):
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Employees / Users
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        role TEXT NOT NULL DEFAULT 'Employee', -- 'Employee', 'Leader', 'Admin'
        telegram_id TEXT,                     -- Numeric Telegram user ID for direct mention
        telegram_username TEXT,               -- Telegram @username
        unit TEXT,                            -- Unit / Department
        work_hours TEXT,                      -- Work hours range
        special_conditions TEXT,              -- JSON list of special conditions
        work_location TEXT,                   -- Physical / remote work location
        position TEXT,                        -- Position / Title
        managed_units TEXT,                   -- JSON list of managed units
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """)

    # 2. Units (e.g. Broadcast, Social, Conductor, Archive, R&D, Management)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        icon TEXT NOT NULL DEFAULT 'layers',
        description TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );
    """)

    # 3. Sections inside Units (e.g. Live Studio, Playlist, Feeds)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE CASCADE,
        UNIQUE (unit_id, name)
    );
    """)

    # 4. Section Managers (Maps who gets automatically notified for incidents in a section)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS section_managers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        is_primary INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE (section_id, user_id)
    );
    """)

    # 5. Incident Reports
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_code TEXT NOT NULL UNIQUE,
        reporter_name TEXT NOT NULL,
        reporter_id INTEGER,
        unit_id INTEGER NOT NULL,
        unit_name TEXT NOT NULL,
        section_id INTEGER,
        section_name TEXT,
        preset_tag TEXT,
        description TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'Normal', -- 'Normal', 'Critical'
        status TEXT NOT NULL DEFAULT 'Pending',   -- 'Pending', 'In Progress', 'Resolved', 'Closed'
        resolution_notes TEXT,
        resolved_by TEXT,
        resolved_at TEXT,
        source TEXT NOT NULL DEFAULT 'Web',       -- 'Web', 'Telegram'
        telegram_chat_id TEXT,
        telegram_update_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE RESTRICT,
        FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE SET NULL
    );
    """)

    # 6. Additional Mentioned Users per Report
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS report_mentions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        user_name TEXT NOT NULL,
        FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE (report_id, user_id)
    );
    """)

    # 7. Telegram Private Message Dispatch Audit Log (Per-Recipient Tracking)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dispatch_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER NOT NULL,
        recipient_role TEXT NOT NULL DEFAULT 'ADMIN', -- 'ADMIN', 'MENTION'
        user_id INTEGER,
        user_name TEXT,
        telegram_id TEXT,
        status TEXT NOT NULL,                         -- 'PENDING', 'SENT', 'FAILED'
        telegram_message_id INTEGER,
        error_message TEXT,
        attempted_at TEXT NOT NULL,
        FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    """)

    # 8. Telegram Account Linking Tokens for Staff Self-Service
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS telegram_link_tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # 9. Admin Credentials & System Settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 10. Dynamic Issue Categories & Presets
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS issue_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        unit_id INTEGER, -- NULL means Global / applies to all units
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE SET NULL,
        UNIQUE (unit_id, name)
    );
    """)

    # 11. Telegram Bot Conversation States
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS telegram_bot_conversations (
        chat_id TEXT PRIMARY KEY,
        user_id INTEGER,
        reporter_name TEXT,
        state TEXT NOT NULL,
        data_json TEXT NOT NULL DEFAULT '{}',
        last_message_id INTEGER,
        updated_at TEXT NOT NULL
    );
    """)

    # 12. Telegram Processed Updates for Webhook / Polling Deduplication
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS telegram_processed_updates (
        update_id INTEGER PRIMARY KEY,
        processed_at TEXT NOT NULL
    );
    """)

    # Check and add columns if upgrading an existing dispatch_logs table
    cursor.execute("PRAGMA table_info(dispatch_logs)")
    existing_cols = {col["name"] for col in cursor.fetchall()}
    if "recipient_role" not in existing_cols:
        cursor.execute("ALTER TABLE dispatch_logs ADD COLUMN recipient_role TEXT DEFAULT 'ADMIN'")
    if "user_id" not in existing_cols:
        cursor.execute("ALTER TABLE dispatch_logs ADD COLUMN user_id INTEGER")
    if "user_name" not in existing_cols:
        cursor.execute("ALTER TABLE dispatch_logs ADD COLUMN user_name TEXT")
    if "telegram_id" not in existing_cols:
        cursor.execute("ALTER TABLE dispatch_logs ADD COLUMN telegram_id TEXT")

    # Check and add columns if upgrading an existing reports table
    cursor.execute("PRAGMA table_info(reports)")
    reports_cols = {col["name"] for col in cursor.fetchall()}
    if "source" not in reports_cols:
        cursor.execute("ALTER TABLE reports ADD COLUMN source TEXT NOT NULL DEFAULT 'Web'")
    if "telegram_chat_id" not in reports_cols:
        cursor.execute("ALTER TABLE reports ADD COLUMN telegram_chat_id TEXT")
    if "telegram_update_id" not in reports_cols:
        cursor.execute("ALTER TABLE reports ADD COLUMN telegram_update_id INTEGER")

    # Check and add profile columns if upgrading an existing users table
    cursor.execute("PRAGMA table_info(users)")
    user_cols = {col["name"] for col in cursor.fetchall()}
    for col_name in ["unit", "work_hours", "special_conditions", "work_location", "position", "managed_units"]:
        if col_name not in user_cols:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} TEXT")

    # Migrate reports table if section_id is NOT NULL
    cursor.execute("PRAGMA table_info(reports)")
    r_cols = {col["name"]: col for col in cursor.fetchall()}
    if "section_id" in r_cols and r_cols["section_id"]["notnull"] == 1:
        cursor.execute("PRAGMA foreign_keys = OFF;")
        cursor.execute("""
        CREATE TABLE reports_migrated (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT NOT NULL UNIQUE,
            reporter_name TEXT NOT NULL,
            reporter_id INTEGER,
            unit_id INTEGER NOT NULL,
            unit_name TEXT NOT NULL,
            section_id INTEGER,
            section_name TEXT,
            preset_tag TEXT,
            description TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'Normal',
            status TEXT NOT NULL DEFAULT 'Pending',
            resolution_notes TEXT,
            resolved_by TEXT,
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE RESTRICT,
            FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE SET NULL
        );
        """)
        cursor.execute("INSERT INTO reports_migrated SELECT * FROM reports;")
        cursor.execute("DROP TABLE reports;")
        cursor.execute("ALTER TABLE reports_migrated RENAME TO reports;")
        cursor.execute("PRAGMA foreign_keys = ON;")

    # Seed Admin Password if not existing
    now_iso = datetime.now().isoformat()
    cursor.execute("SELECT value FROM settings WHERE key = 'admin_password_hash'")
    if not cursor.fetchone():
        hashed_pwd, salt = hash_password(default_admin_password)
        cursor.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('admin_password_hash', ?, ?)", (hashed_pwd, now_iso))
        cursor.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('admin_password_salt', ?, ?)", (salt, now_iso))

    # Always ensure Admin exists in users table (RAL is the unified Admin)
    cursor.execute("SELECT id FROM users WHERE role = 'Admin' OR name = 'RAL'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (name, role, telegram_id, created_at) VALUES ('RAL', 'Admin', '858324589', ?)", (now_iso,))

    # Data Migration: Map legacy report priorities to binary Critical / Normal without data loss
    cursor.execute("""
        UPDATE reports
        SET priority = 'Critical'
        WHERE priority IN ('High', 'Critical')
    """)
    cursor.execute("""
        UPDATE reports
        SET priority = 'Normal'
        WHERE priority NOT IN ('Critical')
    """)

    conn.commit()
    conn.close()

    # Synchronize corporate employees
    sync_corporate_employees_and_structure()

    # Clean units and remove all subsections & issue presets
    sync_clean_units_and_clear_subsections()

def seed_initial_data_if_empty():
    """Populates standard corporate units, sections, and staff based on company structure."""
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()

    # Check if already seeded
    cursor.execute("SELECT COUNT(*) as cnt FROM units")
    if cursor.fetchone()["cnt"] > 0:
        conn.close()
        return

    # Seed Default Employees
    default_employees = [
        ("Admin", "Admin", "Admin_System"),
        ("MMA", "Employee", "MMA_Operator"),
        ("SSA", "Employee", "SSA_Operator"),
        ("STA", "Employee", "STA_Operator"),
        ("ANK", "Employee", "ANK_Operator"),
        ("SAM", "Employee", "SAM_Operator"),
        ("ALA", "Employee", "ALA_Operator"),
        ("SHA", "Employee", "SHA_Operator"),
        ("KKH", "Employee", "KKH_Operator"),
        ("AGO", "Employee", "AGO_Helpdesk"),
        ("SMH", "Employee", "SMH_Conductor"),
        ("RMA", "Employee", "RMA_Conductor"),
        ("AMO", "Employee", "AMO_Conductor"),
        ("MSH", "Employee", "MSH_Playlist")
    ]

    emp_id_map = {}
    for name, role, uname in default_employees:
        cursor.execute("""
        INSERT OR IGNORE INTO users (name, role, telegram_username, created_at)
        VALUES (?, ?, ?, ?)
        """, (name, role, uname, now_iso))
        emp_id_map[name] = cursor.lastrowid

    # Seed Units (Strictly 7 Units without any subsections)
    standard_units = [
        ("Broadcast", "radio", "Playout, live transmission, and studio controls", 10),
        ("Archive & Transfers", "archive", "Media retrieval, digitization, and storage transfers", 20),
        ("Social Media", "share-2", "Content publishing, feeds, and digital platforms", 30),
        ("Conductor & Playlists", "list-video", "Program schedules, automation, and playlists", 40),
        ("Monitoring & OTT", "tv", "Network monitoring, OTT streaming, and feed health", 50),
        ("R&D Services", "cpu", "IT systems, hardware, and software development", 60),
        ("Other", "more-horizontal", "General facility or cross-department incidents", 70)
    ]

    for name, icon, desc, sort in standard_units:
        cursor.execute("""
            INSERT INTO units (name, icon, description, sort_order, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (name, icon, desc, sort, now_iso))

    conn.commit()
    conn.close()

def sync_corporate_employees_and_structure():
    """
    Synchronizes employees with exact working hours, units, conditions, locations,
    and links RAL / Admin to telegram_id 858324589.
    """
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()

    # Corporate Employee Directory provided by organization
    corporate_roster = [
        { 
            "name": "SHA", 
            "unit": "Broadcast", 
            "role": "Employee",
            "work_hours": "15:00 - 23:00", 
            "special_conditions": [], 
            "work_location": "Main Broadcasting Room",
            "position": None
        }, 
        { 
            "name": "MSH", 
            "unit": "Broadcast", 
            "role": "Employee",
            "work_hours": "09:00 - 15:00 & 17:00 - 22:00", 
            "special_conditions": ["Discrete working hours"], 
            "work_location": "Main Broadcasting Room",
            "position": None
        }, 
        { 
            "name": "KKH", 
            "unit": "Broadcast", 
            "role": "Employee",
            "work_hours": "08:00 - 16:00", 
            "special_conditions": [], 
            "work_location": "Home Office",
            "position": None
        }, 
        { 
            "name": "AGO", 
            "unit": "Broadcast", 
            "role": "Employee",
            "work_hours": "10:00 - 18:00", 
            "special_conditions": [], 
            "work_location": "Main Broadcasting Room",
            "position": None
        }, 
        { 
            "name": "MMA", 
            "unit": "All", 
            "role": "Employee",
            "work_hours": "10:00 - 02:00", 
            "special_conditions": ["Multi Task", "Discrete working hours"], 
            "work_location": "Home & Main Broadcasting Room",
            "position": None
        }, 
        { 
            "name": "SSA", 
            "unit": "All", 
            "role": "Employee",
            "work_hours": "08:00 - 16:00 & 00:00 - 02:00", 
            "special_conditions": ["Remote Work", "Discrete working hours"], 
            "work_location": "Home Office",
            "position": None
        }, 
        { 
            "name": "STA", 
            "unit": "Broadcast and R&D", 
            "role": "Employee",
            "work_hours": "16:00 - 24:00", 
            "special_conditions": ["illness"], 
            "work_location": "Home Office",
            "position": None
        }, 
        { 
            "name": "ANK", 
            "unit": "Broadcast and Social Media", 
            "role": "Employee",
            "work_hours": "15:00 - 24:00", 
            "special_conditions": [], 
            "work_location": "Home Office",
            "position": None
        }, 
        { 
            "name": "SAM", 
            "unit": "Conductor", 
            "role": "Employee",
            "work_hours": "Flexible Hours", 
            "special_conditions": [], 
            "work_location": "Home Office",
            "position": None
        }, 
        { 
            "name": "RMA", 
            "unit": "Conductor", 
            "role": "Employee",
            "work_hours": "Flexible Hours", 
            "special_conditions": [], 
            "work_location": "Home Office",
            "position": None
        }, 
        { 
            "name": "SMH", 
            "unit": "Conductor", 
            "role": "Employee",
            "work_hours": "Flexible Hours", 
            "special_conditions": [], 
            "work_location": "Home Office",
            "position": None
        }, 
        { 
            "name": "ALA", 
            "unit": "Archive", 
            "role": "Employee",
            "work_hours": "16:00 - 24:00", 
            "special_conditions": [], 
            "work_location": "Main Archive Room",
            "position": None
        }, 
        { 
            "name": "AMO", 
            "unit": "Conductor", 
            "role": "Employee",
            "work_hours": "17:00 - 20:00", 
            "special_conditions": [], 
            "work_location": "Main Broadcast Room",
            "position": None
        }, 
        { 
            "name": "RAL", 
            "unit": "Management", 
            "role": "Admin", 
            "position": None, 
            "managed_units": ["Broadcast", "Archive", "Playlist", "Social Media"], 
            "work_hours": "00:00 - 24:00", 
            "special_conditions": ["Manager"], 
            "work_location": "Head Office", 
            "telegram_id": "858324589" 
        }
    ]

    for emp in corporate_roster:
        cursor.execute("SELECT id, telegram_id, role FROM users WHERE name = ?", (emp["name"],))
        existing = cursor.fetchone()
        spec_str = json.dumps(emp.get("special_conditions", []))
        managed_str = json.dumps(emp.get("managed_units")) if emp.get("managed_units") else None

        if existing:
            tg_id = emp.get("telegram_id") or existing["telegram_id"]
            role_to_set = emp.get("role") or existing["role"]
            cursor.execute("""
                UPDATE users
                SET unit = ?,
                    work_hours = ?,
                    special_conditions = ?,
                    work_location = ?,
                    position = ?,
                    managed_units = ?,
                    role = ?,
                    telegram_id = ?,
                    is_active = 1
                WHERE id = ?
            """, (
                emp["unit"],
                emp["work_hours"],
                spec_str,
                emp["work_location"],
                emp.get("position"),
                managed_str,
                role_to_set,
                tg_id,
                existing["id"]
            ))
        else:
            cursor.execute("""
                INSERT INTO users (
                    name, role, telegram_id, telegram_username, unit,
                    work_hours, special_conditions, work_location, position,
                    managed_units, is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                emp["name"],
                emp.get("role", "Employee"),
                emp.get("telegram_id"),
                f"{emp['name']}_Staff",
                emp["unit"],
                emp["work_hours"],
                spec_str,
                emp["work_location"],
                emp.get("position"),
                managed_str,
                now_iso
            ))

    # Synchronize Telegram Settings if not already configured
    cursor.execute("SELECT value FROM settings WHERE key = 'admin_telegram_id'")
    curr_adm = cursor.fetchone()
    if not curr_adm or not curr_adm["value"]:
        default_tg = os.getenv("TELEGRAM_CHAT_ID", "").strip() or "-1002756155863"
        cursor.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('admin_telegram_id', ?, ?)", (default_tg, now_iso))
        cursor.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('telegram_chat_id', ?, ?)", (default_tg, now_iso))

    cursor.execute("SELECT value FROM settings WHERE key = 'telegram_bot_token'")
    curr_tok = cursor.fetchone()
    if not curr_tok or not curr_tok["value"]:
        env_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or "7639751548:AAFMxcn66CIAi6Fy3NIDiZzBgqTCuG_tbRY"
        cursor.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('telegram_bot_token', ?, ?)", (env_token, now_iso))

    conn.commit()
    conn.close()

def sync_clean_units_and_clear_subsections():
    """
    Strictly aligns the database with the organization's requirement:
    - Completely clear all sections and section managers
    - Completely clear all issue categories and problem presets
    - Set exactly 7 units without subsections:
      Broadcast, Archive & Transfers, Social Media, Conductor & Playlists, Monitoring & OTT, R&D Services, Other
    - Safeguard historical reports by setting section_id to NULL.
    """
    conn = get_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    cursor.execute("PRAGMA foreign_keys = OFF;")

    # 1. Clear all sections, section_managers, and issue_categories
    cursor.execute("DELETE FROM section_managers")
    cursor.execute("DELETE FROM sections")
    cursor.execute("DELETE FROM issue_categories")

    # 2. Desired 7 units without subsections
    target_units = [
        ("Broadcast", "radio", "Playout, live transmission, and studio controls", 10),
        ("Archive & Transfers", "archive", "Media retrieval, digitization, and storage transfers", 20),
        ("Social Media", "share-2", "Content publishing, feeds, and digital platforms", 30),
        ("Conductor & Playlists", "list-video", "Program schedules, automation, and playlists", 40),
        ("Monitoring & OTT", "tv", "Network monitoring, OTT streaming, and feed health", 50),
        ("R&D Services", "cpu", "IT systems, hardware, and software development", 60),
        ("Other", "more-horizontal", "General facility or cross-department incidents", 70)
    ]

    target_names = [u[0] for u in target_units]

    # Deactivate or remove legacy units that are not part of the target 7
    placeholders = ",".join("?" for _ in target_names)
    cursor.execute(f"UPDATE units SET is_active = 0 WHERE name NOT IN ({placeholders})", target_names)

    # Insert or update each of the 7 target units
    for name, icon, desc, sort in target_units:
        cursor.execute("SELECT id FROM units WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            cursor.execute("""
                UPDATE units
                SET icon = ?, description = ?, sort_order = ?, is_active = 1
                WHERE id = ?
            """, (icon, desc, sort, row["id"]))
        else:
            cursor.execute("""
                INSERT INTO units (name, icon, description, sort_order, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
            """, (name, icon, desc, sort, now_iso))

    # Clean legacy section references in reports
    cursor.execute("UPDATE reports SET section_id = NULL, section_name = NULL")

    conn.commit()
    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.close()
