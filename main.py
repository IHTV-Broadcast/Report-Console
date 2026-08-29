import os
import sys
import json
import uuid
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

from fastapi import FastAPI, HTTPException, Query, Depends, status, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Setup path to import excel_handler and config from Report Bot
BOT_DIR = Path(__file__).resolve().parent / 'Report Bot'
sys.path.append(str(BOT_DIR))

try:
    from excel_handler import save_to_excel
    import config as bot_config
except ImportError as e:
    logging.error(f"Failed to import from Report Bot: {e}")
    # Fallbacks will be defined if imports fail

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ReportConsole")

app = FastAPI(title="Report Console API")

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
ANALYTICS_DIR = Path(__file__).resolve().parent / 'Analytics'
REPORTS_JSON = ANALYTICS_DIR / 'Daily_reports.json'
EMPLOYEES_JSON = BOT_DIR / 'employees_en.json'
EMPLOYEES_FA_JSON = BOT_DIR / 'employees.json'

# Models for Request Bodies
class EmployeeModel(BaseModel):
    id: Optional[int] = None
    name: str = Field(..., min_length=2)
    unit: List[str] = Field(..., min_length=1)
    roles: List[str] = Field(..., min_length=1)
    work_hours: str = Field(...)
    special_conditions: List[str] = Field(default_factory=list)
    work_location: str = Field(...)
    reportsTo: Optional[Union[int, List[int]]] = None
    leader_type: Optional[str] = None
    leader_shift: Optional[str] = None

class ApprovalModel(BaseModel):
    manager_rating: int = Field(..., ge=1, le=10)
    manager_comment: str = Field(default="")
    unit: Optional[str] = None

class ReportUpdateModel(BaseModel):
    date: str
    time: str
    employee: str
    employee_id: int
    unit: str
    rating: int
    mood: str
    additional_info: str = ""
    status: str
    leader_name: Optional[str] = None
    manager_rating: Optional[int] = None
    manager_comment: Optional[str] = ""
    problems: List[dict] = []

# Helpers for Admin PIN configuration
def read_admin_pin() -> str:
    pin_file = BOT_DIR / 'admin_pin.json'
    if not pin_file.exists():
        write_admin_pin("1234")
        return "1234"
    try:
        with open(pin_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("pin", "1234")
    except Exception:
        return "1234"

def write_admin_pin(pin: str) -> bool:
    pin_file = BOT_DIR / 'admin_pin.json'
    try:
        pin_file.parent.mkdir(parents=True, exist_ok=True)
        with open(pin_file, 'w', encoding='utf-8') as f:
            json.dump({"pin": pin}, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False

# Helper to read reports JSON database
def read_reports() -> list:
    if not REPORTS_JSON.exists():
        return []
    try:
        with open(REPORTS_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Error reading reports database: {e}")
        return []

# Helper to write reports JSON database
def write_reports(reports: list) -> bool:
    try:
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        with open(REPORTS_JSON, 'w', encoding='utf-8') as f:
            json.dump(reports, f, ensure_ascii=False, indent=2, default=str)
        return True
    except Exception as e:
        logger.error(f"Error writing reports database: {e}")
        return False

# Default config values injected when keys are missing from the database
DEFAULT_UNITS = ["Broadcast", "Social", "Conductor", "Archive"]
DEFAULT_ROLES = ["Live", "Playlist", "Helpdesk", "Social", "Conductor", "Archive", "R&D", "Leader"]
DEFAULT_SPECIAL_CONDITIONS = [
    "Night Shift", "Remote Work", "Multi Task",
    "Condition Hardship", "Illness", "Discrete Working Hours", "General Requirements"
]

# Helper to check circular reporting chains (A -> B -> C -> A)
def check_reporting_cycle(employees: list, emp_id: int, target_supervisor_ids: Union[int, List[int], None]) -> bool:
    if not target_supervisor_ids:
        return False
    
    if isinstance(target_supervisor_ids, list):
        ids_to_check = [int(x) for x in target_supervisor_ids if x is not None]
    else:
        ids_to_check = [int(target_supervisor_ids)]

    emp_map = {e.get("id"): e for e in employees if e.get("id") is not None}

    for start_id in ids_to_check:
        visited = set()
        queue = [start_id]
        while queue:
            curr = queue.pop(0)
            if curr == emp_id:
                return True
            if curr in visited:
                continue
            visited.add(curr)
            
            supervisor = emp_map.get(curr)
            if supervisor:
                sups = supervisor.get("reportsTo") or supervisor.get("reports_to") or []
                if isinstance(sups, list):
                    for s in sups:
                        if s is not None:
                            queue.append(int(s))
                else:
                    queue.append(int(sups))
    return False

# Helper to read employees JSON database
def read_employees(english: bool = True) -> dict:
    file_path = EMPLOYEES_JSON if english else EMPLOYEES_FA_JSON
    if not file_path.exists():
        # Fallback to the other one if one is missing
        file_path = EMPLOYEES_FA_JSON if english else EMPLOYEES_JSON
        if not file_path.exists():
            return {"employees": []}
            
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Inject defaults for dynamic config keys if not yet persisted
        if "units" not in data:
            data["units"] = DEFAULT_UNITS
        if "roles" not in data:
            data["roles"] = DEFAULT_ROLES
        if "special_conditions" not in data:
            data["special_conditions"] = DEFAULT_SPECIAL_CONDITIONS
            
        # Ensure all employees have unique numeric id and reportsTo properties
        employees = data.get("employees", [])
        assigned_ids = set()
        next_id = 1
        for emp in employees:
            if "id" in emp and emp["id"] is not None:
                assigned_ids.add(int(emp["id"]))
        for emp in employees:
            if "id" not in emp or emp["id"] is None:
                while next_id in assigned_ids:
                    next_id += 1
                emp["id"] = next_id
                assigned_ids.add(next_id)
            if "reportsTo" not in emp:
                emp["reportsTo"] = emp.get("reports_to", [])
            
            # Normalize to list of integers
            rep_val = emp["reportsTo"]
            if rep_val is None:
                emp["reportsTo"] = []
            elif isinstance(rep_val, list):
                emp["reportsTo"] = [int(x) for x in rep_val if x is not None]
            else:
                emp["reportsTo"] = [int(rep_val)]
        
        return data
    except Exception as e:
        logger.error(f"Error reading employees database ({file_path.name}): {e}")
        return {"employees": []}

# Helper to write employees JSON database
def write_employees(data: dict, english: bool = True) -> bool:
    file_path = EMPLOYEES_JSON if english else EMPLOYEES_FA_JSON
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error writing employees database ({file_path.name}): {e}")
        return False

# In-memory session store
SESSIONS: Dict[str, dict] = {}

class LoginModel(BaseModel):
    username: str
    pin: Optional[str] = None

# ----------------- AUTH ENDPOINTS -----------------
@app.post("/api/auth/login")
async def login(payload: LoginModel):
    raw_user = payload.username.strip()
    if not raw_user:
        raise HTTPException(status_code=400, detail="Username is required.")

    # 1. Administrator Login ("RAL")
    if raw_user.upper() == "RAL":
        stored_pin = read_admin_pin()
        if not payload.pin:
            raise HTTPException(status_code=401, detail="PIN_REQUIRED")
        if payload.pin.strip() != stored_pin:
            raise HTTPException(status_code=401, detail="INCORRECT_PIN")
            
        token = str(uuid.uuid4())
        session_info = {
            "token": token,
            "username": "RAL",
            "name": "Administrator (RAL)",
            "role": "Admin",
            "emp_id": None,
            "created_at": datetime.now().isoformat()
        }
        SESSIONS[token] = session_info
        return session_info

    # 2. Employee / Leader Database Search
    data_en = read_employees(english=True)
    employees = data_en.get("employees", [])
    emp = next((e for e in employees if (e.get("name") or "").strip().lower() == raw_user.lower() or str(e.get("id")) == raw_user), None)

    if not emp:
        raise HTTPException(status_code=404, detail="Username not found.")

    roles = emp.get("roles", [])
    role_tier = "Leader" if (isinstance(roles, list) and "Leader" in roles) else "Employee"

    token = str(uuid.uuid4())
    session_info = {
        "token": token,
        "username": emp.get("name"),
        "name": emp.get("name"),
        "role": role_tier,
        "emp_id": emp.get("id"),
        "created_at": datetime.now().isoformat()
    }
    SESSIONS[token] = session_info
    return session_info

@app.get("/api/auth/me")
async def get_me(
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    x_user_name: Optional[str] = Header(None, alias="X-User-Name")
):
    if x_session_token and x_session_token in SESSIONS:
        return SESSIONS[x_session_token]
    
    if x_user_name:
        role_ctx = get_user_role_context(x_session_token=None, x_user_name=x_user_name)
        return {
            "token": "legacy",
            "username": role_ctx[0],
            "name": role_ctx[0],
            "role": role_ctx[1]
        }
        
    raise HTTPException(status_code=401, detail="Unauthenticated")

@app.post("/api/auth/logout")
async def logout(x_session_token: Optional[str] = Header(None, alias="X-Session-Token")):
    if x_session_token and x_session_token in SESSIONS:
        del SESSIONS[x_session_token]
    return {"message": "Logged out successfully"}

# Helper to extract caller role context from session token or header
def get_user_role_context(
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    x_user_name: Optional[str] = Header(None, alias="X-User-Name")
):
    """
    Returns tuple: (user_name, role_tier, employee_dict)
    role_tier is one of: "Admin", "Leader", "Employee"
    """
    if x_session_token and x_session_token in SESSIONS:
        sess = SESSIONS[x_session_token]
        user_name = sess["username"]
        role_tier = sess["role"]
        emp = None
        if sess.get("emp_id"):
            data = read_employees(english=True)
            emp = next((e for e in data.get("employees", []) if e.get("id") == sess["emp_id"]), None)
        return (user_name, role_tier, emp)

    if x_user_name:
        if x_user_name.strip().upper() == "RAL" or x_user_name.strip().lower() in ["admin", "administrator"]:
            return ("Administrator (RAL)", "Admin", None)

        data = read_employees(english=True)
        employees = data.get("employees", [])
        emp = next((e for e in employees if (e.get("name") or "").strip().lower() == x_user_name.strip().lower() or str(e.get("id")) == str(x_user_name)), None)
        if emp:
            roles = emp.get("roles", [])
            role_tier = "Leader" if (isinstance(roles, list) and "Leader" in roles) else "Employee"
            return (emp.get("name"), role_tier, emp)
        return (x_user_name, "Admin", None)

    return ("Administrator (RAL)", "Admin", None)

class ChangePinModel(BaseModel):
    current_pin: str
    new_pin: str

# 1. Change Admin PIN endpoint
@app.post("/api/admin/change-pin")
async def change_admin_pin(payload: ChangePinModel, user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    if role_tier != "Admin":
        raise HTTPException(status_code=403, detail="Access denied. Only Administrators can change the Admin PIN.")
        
    stored_pin = read_admin_pin()
    if payload.current_pin.strip() != stored_pin:
        raise HTTPException(status_code=400, detail="Current PIN is incorrect.")
        
    new_pin_clean = payload.new_pin.strip()
    if not new_pin_clean:
        raise HTTPException(status_code=400, detail="New PIN cannot be empty.")
        
    if len(new_pin_clean) < 4:
        raise HTTPException(status_code=400, detail="New PIN must be at least 4 characters long.")
        
    if write_admin_pin(new_pin_clean):
        return {"message": "Admin PIN updated successfully."}
    else:
        raise HTTPException(status_code=500, detail="Failed to write PIN config file.")

# 1. Config endpoint
@app.get("/api/config")
async def get_config():
    """Retrieve system configuration options"""
    try:
        return {
            "servers": getattr(bot_config, "SERVERS", []),
            "problem_categories": getattr(bot_config, "PROBLEM_CATEGORIES", []),
            "problem_subcategories": getattr(bot_config, "PROBLEM_SUBCATEGORIES", {}),
            "work_sections": getattr(bot_config, "WORK_SECTIONS", []),
            "live_event_sources": getattr(bot_config, "LIVE_EVENT_SOURCES", [])
        }
    except Exception as e:
        logger.error(f"Error retrieving config: {e}")
        # Default fallbacks
        return {
            "servers": ["Farsi", "Arabic", "English", "Urdu", "Turki", "Live", "Other"],
            "problem_categories": ["Broadcast", "Conductor", "Social Media", "Archive"],
            "problem_subcategories": {},
            "work_sections": ["Live", "Archive", "Conductor", "Social Media", "Playlist", "Monitoring", "Support"],
            "live_event_sources": ["Controls", "Servers", "Internet", "Other"]
        }

def normalize_mood(mood_raw: str) -> str:
    """Normalize raw mood strings to 3 official states: Happy, Normal, Sad"""
    if not mood_raw:
        return "😐 Normal"
    m_lower = str(mood_raw).lower()
    if any(k in m_lower for k in ["happy", "great", "good", "excellent", "high energy", "😄", "😊", "😃", "😁"]):
        return "😄 Happy"
    elif any(k in m_lower for k in ["sad", "bad", "tired", "upset", "stressed", "hard", "😔", "🙁", "☹️", "😢"]):
        return "😔 Sad"
    else:
        return "😐 Normal"

def normalize_category(cat_raw: str) -> str:
    """Normalize problem categories to the 7 official system categories"""
    if not cat_raw:
        return "live"
    c_lower = str(cat_raw).strip().lower()
    if "r&d" in c_lower or "rd" in c_lower or "research" in c_lower:
        return "r&d"
    elif "play" in c_lower or "playlist" in c_lower:
        return "play list"
    elif "help" in c_lower or "helpdesk" in c_lower:
        return "helpdesk"
    elif "social" in c_lower:
        return "social"
    elif "conduct" in c_lower:
        return "conductor"
    elif "arch" in c_lower:
        return "archive"
    elif "live" in c_lower or "broadcast" in c_lower:
        return "live"
    else:
        return "live"

# 2. Statistics endpoint
@app.get("/api/stats")
async def get_stats(user_context: tuple = Depends(get_user_role_context)):
    """Retrieve analytics and stats for the dashboard"""
    user_name, role_tier, emp = user_context
    reports = read_reports()
    
    # Filter reports for scoping
    if role_tier == "Employee":
        reports = [r for r in reports if (r.get("data", {}).get("employee") or "").strip().lower() == user_name.strip().lower()]
    elif role_tier == "Leader" and emp is not None:
        data_en = read_employees(english=True)
        leader_id = str(emp.get("id"))
        leader_name = (emp.get("name") or "").strip().lower()
        team_names = set()
        
        for e in data_en.get("employees", []):
            rep_to = e.get("reportsTo") or e.get("reports_to") or []
            is_match = False
            if isinstance(rep_to, list):
                if any(str(x).strip() == leader_id for x in rep_to if x is not None):
                    is_match = True
            elif rep_to is not None:
                if str(rep_to).strip() == leader_id or str(rep_to).strip().lower() == leader_name:
                    is_match = True

            if is_match:
                e_name = (e.get("name") or "").strip().lower()
                if e_name:
                    team_names.add(e_name)

        team_names.add(user_name.strip().lower())
        reports = [r for r in reports if (r.get("data", {}).get("employee") or r.get("employee") or "").strip().lower() in team_names]
        
    total = len(reports)
    pending = len([r for r in reports if r.get('status') == 'pending'])
    approved = len([r for r in reports if r.get('status') == 'approved'])
    
    problem_reports = 0
    normal_reports = 0
    for r in reports:
        report_data = r.get('data', {})
        problems = report_data.get('problems', [])
        if problems or r.get('status') == 'مشکل':
            problem_reports += 1
        else:
            normal_reports += 1
            
    # Average ratings
    total_manager_ratings = 0
    manager_ratings_sum = 0
    total_employee_ratings = 0
    employee_ratings_sum = 0
    
    # Mood counts
    mood_counts = {
        "😄 Happy": 0,
        "😐 Normal": 0,
        "😔 Sad": 0
    }
    
    # Category counts
    category_counts = {
        "r&d": 0,
        "live": 0,
        "play list": 0,
        "helpdesk": 0,
        "social": 0,
        "conductor": 0,
        "archive": 0
    }
    
    # Server workload
    server_counts = {}
    
    # Employee stats mapping
    employee_stats = {}
    
    # Daily timeline (last 14 days)
    timeline_days = 14
    today = datetime.now().date()
    date_list = [today - timedelta(days=x) for x in range(timeline_days)]
    date_list.reverse()
    
    timeline_data = {d.isoformat(): {"total": 0, "problems": 0} for d in date_list}
    
    for r in reports:
        report_data = r.get('data', {})
        emp_name = report_data.get('employee', 'Unknown')
        
        # Ratings
        emp_rating = report_data.get('rating')
        if emp_rating is not None:
            try:
                employee_ratings_sum += float(emp_rating)
                total_employee_ratings += 1
            except ValueError:
                pass
                
        mgr_rating = r.get('manager_rating') or report_data.get('manager_rating')
        if mgr_rating is not None:
            try:
                manager_ratings_sum += float(mgr_rating)
                total_manager_ratings += 1
            except ValueError:
                pass
                
        # Mood
        raw_mood = report_data.get('mood') or r.get('mood')
        if raw_mood:
            n_mood = normalize_mood(raw_mood)
            mood_counts[n_mood] += 1
            
        # Employee specific stats
        if emp_name not in employee_stats:
            employee_stats[emp_name] = {
                "reports_count": 0,
                "problems_count": 0,
                "ratings_sum": 0,
                "ratings_count": 0
            }
        employee_stats[emp_name]["reports_count"] += 1
        if emp_rating is not None:
            try:
                employee_stats[emp_name]["ratings_sum"] += float(emp_rating)
                employee_stats[emp_name]["ratings_count"] += 1
            except ValueError:
                pass
        
        # Problems & categories
        problems = report_data.get('problems', [])
        has_prob = len(problems) > 0
        if has_prob:
            employee_stats[emp_name]["problems_count"] += 1
            for p in problems:
                cat_raw = p.get('type') or p.get('category') or p.get('section') or report_data.get('section') or 'live'
                cat_norm = normalize_category(cat_raw)
                category_counts[cat_norm] = category_counts.get(cat_norm, 0) + 1
                
        # Server distribution
        servers = report_data.get('servers', [])
        for s in servers:
            server_counts[s] = server_counts.get(s, 0) + 1
            
        # Timeline grouping
        created_at_str = r.get('created_at') or r.get('timestamp')
        if created_at_str:
            try:
                # Handle ISO format
                created_date = datetime.fromisoformat(created_at_str.split('T')[0]).date()
                date_iso = created_date.isoformat()
                if date_iso in timeline_data:
                    timeline_data[date_iso]["total"] += 1
                    if has_prob:
                        timeline_data[date_iso]["problems"] += 1
            except Exception:
                pass
                
    # Formatting Timeline for Chart.js
    labels = list(timeline_data.keys())
    timeline_totals = [v["total"] for v in timeline_data.values()]
    timeline_problems = [v["problems"] for v in timeline_data.values()]
    
    # Calculate Averages
    avg_manager = round(manager_ratings_sum / total_manager_ratings, 2) if total_manager_ratings > 0 else 0.0
    avg_employee = round(employee_ratings_sum / total_employee_ratings, 2) if total_employee_ratings > 0 else 0.0
    
    # Format employee leaderboard (30 days ranking by highest rating & lowest missing reports)
    data_en = read_employees(english=True)
    all_employees = data_en.get("employees", [])
    
    today_date = datetime.now().date()
    past_30_days = {today_date - timedelta(days=i) for i in range(30)}

    # Initialize leaderboard map: keyed by (employee_name.lower(), unit.lower())
    emp_leaderboard_map = {}
    
    for e in all_employees:
        n = (e.get("name") or "").strip()
        if not n:
            continue
        emp_units = get_employee_authorized_units(e)
        for u in emp_units:
            key = (n.lower(), u.lower())
            emp_leaderboard_map[key] = {
                "name": n,
                "unit": u.capitalize(),
                "submitted_dates": set(),
                "ratings": [],
                "reports_count": 0,
                "problems_count": 0
            }

    for r in reports:
        r_data = r.get("data", {}) or {}
        emp_name_raw = r_data.get("employee") or r.get("employee") or r_data.get("name") or ""
        emp_name_clean = emp_name_raw.strip().lower()
        if not emp_name_clean:
            continue

        target_emp = next((e for e in all_employees if (e.get("name") or "").strip().lower() == emp_name_clean), None)
        if not target_emp:
            continue
            
        emp_units = get_employee_authorized_units(target_emp)
        
        # Check date in past 30 days
        date_str = r.get("created_at") or r.get("timestamp") or r.get("submitted_at") or ""
        is_in_past_30 = False
        r_date = None
        if date_str:
            try:
                r_date = datetime.fromisoformat(str(date_str).split("T")[0]).date()
                if r_date in past_30_days:
                    is_in_past_30 = True
            except Exception:
                pass

        problems = r_data.get("problems") or r.get("problems") or []
        units_in_report = set()
        for p in problems:
            p_cat = (p.get("category") or p.get("type") or "").strip().lower()
            if p_cat:
                for u in emp_units:
                    if p_cat == u or p_cat in u or u in p_cat:
                        units_in_report.add(u)
                        break
                        
        if not units_in_report:
            units_in_report = emp_units

        for u in units_in_report:
            key = (emp_name_clean, u.lower())
            if key not in emp_leaderboard_map:
                emp_leaderboard_map[key] = {
                    "name": target_emp.get("name") or emp_name_raw,
                    "unit": u.capitalize(),
                    "submitted_dates": set(),
                    "ratings": [],
                    "reports_count": 0,
                    "problems_count": 0
                }
            if is_in_past_30 and r_date:
                emp_leaderboard_map[key]["submitted_dates"].add(r_date)
            emp_leaderboard_map[key]["reports_count"] += 1
            has_prob_for_unit = False
            for p in problems:
                p_cat = (p.get("category") or p.get("type") or "").strip().lower()
                if p_cat and (p_cat == u or p_cat in u or u in p_cat):
                    has_prob_for_unit = True
                    break
            if has_prob_for_unit:
                emp_leaderboard_map[key]["problems_count"] += 1

        # Collect leader ratings from leader_scores, averaging multiples in the same report
        scores = get_report_leader_scores(r, all_employees)
        unit_scores_map = {}
        for s in scores:
            s_unit = s.get("unit")
            if s_unit:
                s_unit = s_unit.strip().lower()
                matching_unit = None
                for u in emp_units:
                    if s_unit == u or s_unit in u or u in s_unit:
                        matching_unit = u
                        break
                if matching_unit:
                    if matching_unit not in unit_scores_map:
                        unit_scores_map[matching_unit] = []
                    unit_scores_map[matching_unit].append(s["score"])
                    
        for u, val_list in unit_scores_map.items():
            if val_list:
                key = (emp_name_clean, u.lower())
                if key in emp_leaderboard_map:
                    emp_leaderboard_map[key]["ratings"].append(sum(val_list) / len(val_list))

    leaderboard = []
    for key, item in emp_leaderboard_map.items():
        ratings = item["ratings"]
        avg_score = round(sum(ratings) / len(ratings), 2) if len(ratings) > 0 else 0.0
        missing_cnt = 30 - len(item["submitted_dates"])
        leaderboard.append({
            "name": item["name"],
            "unit": item["unit"],
            "avg_rating": avg_score,
            "missing_reports": missing_cnt,
            "reports": item["reports_count"],
            "problems": item["problems_count"]
        })

    # Sort strictly by: 1) Highest Rating  2) Lowest Missing Reports  3) Highest Total Submissions
    leaderboard.sort(key=lambda x: (x["avg_rating"], -x["missing_reports"], x["reports"]), reverse=True)
    
    # Calculate Best Employee per Unit ("Man of the <Unit>")
    unit_champions = []
    unit_categories = ["Broadcast", "Conductor", "Archive", "Social Media", "R&D"]

    for unit_name in unit_categories:
        unit_key = unit_name.lower()
        candidates = []
        for item in leaderboard:
            u_name = str(item.get("unit") or "").lower()
            matches = False
            if unit_key == "social media" and ("social" in u_name):
                matches = True
            elif unit_key == "r&d" and ("rd" in u_name or "r&d" in u_name or "research" in u_name):
                matches = True
            elif unit_key in u_name:
                matches = True

            if matches and item.get("avg_rating", 0.0) > 0.0:
                candidates.append(item)

        if candidates:
            candidates.sort(
                key=lambda x: (
                    x["avg_rating"],
                    -x["missing_reports"],
                    x["reports"]
                ),
                reverse=True
            )
            top_emp = candidates[0]
            unit_champions.append({
                "title": f"Man of the {unit_name}",
                "unit": unit_name,
                "name": top_emp["name"],
                "avg_rating": top_emp["avg_rating"],
                "missing_reports": top_emp["missing_reports"],
                "reports": top_emp["reports"],
                "problems": top_emp["problems"]
            })

    return {
        "summary": {
            "total_reports": total,
            "pending_approvals": pending,
            "approved_reports": approved,
            "problem_reports": problem_reports,
            "normal_reports": normal_reports,
            "avg_manager_rating": avg_manager,
            "avg_employee_rating": avg_employee
        },
        "mood_distribution": mood_counts,
        "issue_categories": category_counts,
        "server_workload": server_counts,
        "employee_leaderboard": leaderboard,
        "unit_champions": unit_champions,
        "timeline": {
            "labels": labels,
            "totals": timeline_totals,
            "problems": timeline_problems
        }
    }

# 2b. Missing Reports per Unit (today's unreported employees)
@app.get("/api/stats/missing-reports")
async def get_missing_reports(user_context: tuple = Depends(get_user_role_context)):
    """Return count of employees who have NOT submitted a report today, grouped by unit"""
    user_name, role_tier, emp = user_context
    data_en = read_employees(english=True)
    all_employees = data_en.get("employees", [])
    reports = read_reports()

    today_str = datetime.now().date().isoformat()

    # Find names of employees who submitted at least one report today
    submitted_today = set()
    for r in reports:
        created_at = r.get("created_at") or r.get("timestamp") or ""
        if created_at.startswith(today_str):
            emp_name = (r.get("data", {}).get("employee") or "").strip().lower()
            if emp_name:
                submitted_today.add(emp_name)

    # Group missing reporters by unit
    unit_missing = {}
    unit_total = {}
    for e in all_employees:
        raw_unit = e.get("unit") or "Unknown"
        # unit can be a list (e.g. ["Broadcast", "Social Media"]) — normalise to str
        if isinstance(raw_unit, list):
            unit = ", ".join(raw_unit) if raw_unit else "Unknown"
        else:
            unit = str(raw_unit).strip() or "Unknown"
        name = (e.get("name") or "").strip().lower()
        unit_total[unit] = unit_total.get(unit, 0) + 1
        if name and name not in submitted_today:
            unit_missing[unit] = unit_missing.get(unit, 0) + 1

    # Ensure every unit appears even if all submitted
    for unit in unit_total:
        if unit not in unit_missing:
            unit_missing[unit] = 0

    return {
        "missing_by_unit": unit_missing,
        "total_by_unit": unit_total,
        "submitted_today": len(submitted_today),
        "total_employees": len(all_employees),
        "date": today_str
    }

# Helper to retrieve all authorized categories/units for an employee
def get_employee_authorized_units(emp: dict) -> set:
    if not emp:
        return set()
    authorized = set()
    
    # 1. Add units
    units = emp.get("unit") or []
    if isinstance(units, str):
        units = [units]
    for u in units:
        if u:
            u_clean = str(u).strip().lower()
            authorized.add(u_clean)
            if "social" in u_clean:
                authorized.add("social")
            if "r&d" in u_clean or "r & d" in u_clean:
                authorized.add("r&d")
                
    # 2. Add roles
    roles = emp.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    for r in roles:
        if r:
            r_clean = str(r).strip().lower()
            if r_clean != "leader":
                authorized.add(r_clean)
                if "social" in r_clean:
                    authorized.add("social")
                if "r&d" in r_clean or "r & d" in r_clean:
                    authorized.add("r&d")
                    
    # Normalize/Filter against valid categories list
    valid_categories = {'broadcast', 'conductor', 'archive', 'social', 'r&d', 'live', 'playlist', 'helpdesk'}
    normalized_auth = set()
    for item in authorized:
        for cat in valid_categories:
            if cat == item or cat in item or item in cat:
                normalized_auth.add(cat)
                
    return normalized_auth

# Helper to determine leader access to a report (including cross-category problems)
def get_report_visibility_for_user(user_name: str, role_tier: str, emp: dict, report: dict, employees_list: list) -> Optional[dict]:
    """
    Centralized visibility and routing logic.
    Returns the filtered report dict if user has access to it, or None if no access is allowed.
    """
    if not user_name:
        return None

    # Admin / RAL has full access to the complete original report
    if role_tier == "Admin" or user_name.strip().upper() == "RAL":
        return report

    # Employee scoping: can only see their own reports
    if role_tier == "Employee":
        r_data = report.get("data") or {}
        rep_emp = (r_data.get("employee") or report.get("employee") or "").strip().lower()
        if rep_emp == user_name.strip().lower():
            return report
        return None

    # Leader scoping
    if role_tier == "Leader":
        if not emp:
            return None

        leader_id = str(emp.get("id"))
        leader_name = (emp.get("name") or "").strip().lower()
        r_data = report.get("data") or {}
        rep_emp = (r_data.get("employee") or report.get("employee") or "").strip().lower()
        rep_emp_id = str(r_data.get("employee_id") or report.get("employee_id") or "")

        # A leader can always access reports they submitted themselves
        if rep_emp == leader_name or rep_emp_id == leader_id:
            return report

        # Find reporter's profile in employees list
        target_emp = next((e for e in employees_list if (e.get("name") or "").strip().lower() == rep_emp or str(e.get("id")) == rep_emp_id), None)
        if not target_emp:
            return None

        # Get reporter's supervisor configuration
        rep_to = target_emp.get("reportsTo") or target_emp.get("reports_to") or []
        if not isinstance(rep_to, list):
            rep_to = [rep_to]
        rep_to_clean = [str(x).strip() for x in rep_to if x is not None]

        # Get leader's categories/units
        valid_categories = {'broadcast', 'conductor', 'archive', 'social', 'r&d', 'live', 'playlist', 'helpdesk'}

        def get_leader_categories(emp_dict: dict) -> set:
            cats = set()
            roles = emp_dict.get("roles") or []
            if not isinstance(roles, list):
                roles = [roles]
            units = emp_dict.get("unit") or []
            if not isinstance(units, list):
                units = [units]
            l_type = str(emp_dict.get("leader_type") or "").lower()

            for r in roles:
                r_clean = str(r).strip().lower()
                if r_clean in valid_categories:
                    cats.add(r_clean)
            for u in units:
                u_clean = str(u).strip().lower()
                if "social" in u_clean:
                    cats.add("social")
                for cat in valid_categories:
                    if cat in u_clean:
                        cats.add(cat)
            for cat in valid_categories:
                if cat in l_type:
                    cats.add(cat)
            return cats

        leader_cats = get_leader_categories(emp)

        # Enforce subordinate employee unit authorization
        emp_auth_units = get_employee_authorized_units(target_emp)

        problems = r_data.get("problems") or report.get("problems") or []

        # If a report has no problems (clean shift), only direct supervisors have access
        if not problems:
            is_direct_subordinate = any(x == leader_id or x.lower() == leader_name for x in rep_to_clean)
            if is_direct_subordinate:
                return report
            return None

        # Filter problems based on unit authorization and leader routing rules
        import copy
        filtered_problems = []
        for prob in problems:
            if not isinstance(prob, dict):
                continue
            prob_cat = (prob.get("category") or prob.get("type") or "").strip().lower()
            if not prob_cat:
                continue

            # Enforce employee unit authorization
            is_emp_auth = False
            for u in emp_auth_units:
                if prob_cat == u or prob_cat in u or u in prob_cat:
                    is_emp_auth = True
                    break
            if not is_emp_auth:
                continue

            # Find matching assigned leaders in subordinate list
            assigned_leaders_for_unit = []
            for l_id in rep_to_clean:
                l_emp = next((e for e in employees_list if str(e.get("id")) == str(l_id) or (e.get("name") or "").strip().lower() == l_id.lower()), None)
                if l_emp:
                    l_cats = get_leader_categories(l_emp)
                    is_match = False
                    for c in l_cats:
                        if c == prob_cat or c in prob_cat or prob_cat in c:
                            is_match = True
                            break
                    if is_match:
                        assigned_leaders_for_unit.append(l_emp)

            # Routing rule logic
            if assigned_leaders_for_unit:
                is_assigned = any(str(l.get("id")) == leader_id or (l.get("name") or "").strip().lower() == leader_name for l in assigned_leaders_for_unit)
                if is_assigned:
                    filtered_problems.append(prob)
            else:
                is_match = False
                for c in leader_cats:
                    if c == prob_cat or c in prob_cat or prob_cat in c:
                        is_match = True
                        break
                if is_match:
                    filtered_problems.append(prob)

        # If no problems remain for this leader, they have no visibility/access to this report
        if not filtered_problems:
            return None

        # Return deep copied filtered report
        filtered_report = copy.deepcopy(report)
        if "problems" in filtered_report:
            filtered_report["problems"] = filtered_problems
        if "data" in filtered_report:
            filtered_report["data"]["problems"] = filtered_problems
        return filtered_report

    return None

# Helper to determine leader access to a report (including cross-category problems)
def check_leader_report_access(leader_emp: dict, report: dict, employees_list: list) -> bool:
    vis = get_report_visibility_for_user(leader_emp.get("name"), "Leader", leader_emp, report, employees_list)
    return vis is not None

# Helper to filter report content to only include unit-specific problems routed to the leader
def filter_report_for_leader(leader_emp: dict, report: dict, employees_list: list) -> dict:
    vis = get_report_visibility_for_user(leader_emp.get("name"), "Leader", leader_emp, report, employees_list)
    return vis if vis is not None else report

# Helper to determine if a pending report should go to Admin/RAL as fallback review
def is_report_pending_for_admin(report: dict, employees_list: list) -> bool:
    r_data = report.get("data") or {}
    emp_name = (r_data.get("employee") or report.get("employee") or "").strip().lower()
    emp_id_str = str(r_data.get("employee_id") or report.get("employee_id") or "")
    
    target_emp = next((e for e in employees_list if (e.get("name") or "").strip().lower() == emp_name or str(e.get("id")) == emp_id_str), None)
    if not target_emp:
        return True
        
    rep_to = target_emp.get("reportsTo") or target_emp.get("reports_to") or []
    if not isinstance(rep_to, list):
        rep_to = [rep_to]
    rep_to_clean = [str(x).strip() for x in rep_to if x is not None]
    
    if not rep_to_clean:
        return True
        
    problems = r_data.get("problems") or report.get("problems") or []
    if not problems:
        return False
        
    emp_auth_units = get_employee_authorized_units(target_emp)
    valid_categories = {'broadcast', 'conductor', 'archive', 'social', 'r&d', 'live', 'playlist', 'helpdesk'}
    
    def get_leader_categories(emp_dict: dict) -> set:
        cats = set()
        roles = emp_dict.get("roles") or []
        if not isinstance(roles, list):
            roles = [roles]
        units = emp_dict.get("unit") or []
        if not isinstance(units, list):
            units = [units]
        l_type = str(emp_dict.get("leader_type") or "").lower()
        
        for r in roles:
            r_clean = str(r).strip().lower()
            if r_clean in valid_categories:
                cats.add(r_clean)
        for u in units:
            u_clean = str(u).strip().lower()
            if "social" in u_clean:
                cats.add("social")
            for cat in valid_categories:
                if cat in u_clean:
                    cats.add(cat)
        for cat in valid_categories:
            if cat in l_type:
                cats.add(cat)
        return cats

    for prob in problems:
        if not isinstance(prob, dict):
            continue
        prob_cat = (prob.get("category") or prob.get("type") or "").strip().lower()
        if not prob_cat:
            continue
            
        is_emp_auth = False
        for u in emp_auth_units:
            if prob_cat == u or prob_cat in u or u in prob_cat:
                is_emp_auth = True
                break
        if not is_emp_auth:
            continue
            
        assigned_leaders_for_unit = []
        for l_id in rep_to_clean:
            l_emp = next((e for e in employees_list if str(e.get("id")) == str(l_id) or (e.get("name") or "").strip().lower() == l_id.lower()), None)
            if l_emp:
                l_cats = get_leader_categories(l_emp)
                is_match = False
                for c in l_cats:
                    if c == prob_cat or c in prob_cat or prob_cat in c:
                        is_match = True
                        break
                if is_match:
                    assigned_leaders_for_unit.append(l_emp)
                    
        if not assigned_leaders_for_unit:
            return True
    return False

# Helper to retrieve unit-specific leader scores (resolving legacy ratings if needed)
def get_report_leader_scores(report: dict, employees_list: list) -> list:
    """
    Retrieves leader score entries for a report, mapping legacy manager_rating/feedback
    to units dynamically (without guessing) to preserve historical data.
    """
    if "leader_scores" in report:
        return report["leader_scores"]
    r_data = report.get("data") or {}
    if "leader_scores" in r_data:
        return r_data["leader_scores"]
        
    legacy_rating = report.get("manager_rating") or r_data.get("manager_rating")
    if legacy_rating is None:
        return []
        
    try:
        score = float(legacy_rating)
    except (ValueError, TypeError):
        return []
        
    feedback = report.get("manager_feedback") or r_data.get("manager_feedback") or {}
    leader_name = feedback.get("manager_id") or report.get("leader_name") or "unknown"
    leader_id = str(feedback.get("manager_id") or "")
    
    problems = r_data.get("problems") or report.get("problems") or []
    emp_name = (r_data.get("employee") or report.get("employee") or "").strip().lower()
    emp_id_str = str(r_data.get("employee_id") or report.get("employee_id") or "")
    target_emp = next((e for e in employees_list if (e.get("name") or "").strip().lower() == emp_name or str(e.get("id")) == emp_id_str), None)
    
    unit = None
    if problems:
        units_in_problems = set()
        for p in problems:
            p_cat = (p.get("category") or p.get("type") or "").strip().lower()
            if p_cat:
                units_in_problems.add(p_cat)
        if len(units_in_problems) == 1:
            unit = list(units_in_problems)[0]
    else:
        if target_emp:
            emp_units = get_employee_authorized_units(target_emp)
            if len(emp_units) == 1:
                unit = list(emp_units)[0]
                
    return [{
        "unit": unit,
        "leader_id": leader_id,
        "leader_name": leader_name,
        "score": score,
        "comment": feedback.get("comment") or report.get("manager_comment") or "",
        "timestamp": feedback.get("timestamp") or report.get("updated_at") or ""
    }]

# 3. List reports with filters and RBAC permission scoping
@app.get("/api/reports")
async def get_reports(
    status: Optional[str] = None,
    employee: Optional[str] = None,
    server: Optional[str] = None,
    category: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user_context: tuple = Depends(get_user_role_context)
):
    """List reports with filter options and role-based scoping"""
    user_name, role_tier, emp = user_context
    reports = read_reports()
    
    # Filter to approved reports only
    reports = [r for r in reports if r.get('status') == 'approved']

    # Scoping per role tier
    if role_tier == "Employee":
        reports = [r for r in reports if (r.get("data", {}).get("employee") or "").strip().lower() == user_name.strip().lower()]
    elif role_tier == "Leader" and emp is not None:
        data_en = read_employees(english=True)
        emp_list = data_en.get("employees", [])
        reports = [r for r in reports if check_leader_report_access(emp, r, emp_list)]
        reports = [filter_report_for_leader(emp, r, emp_list) for r in reports]

    filtered_reports = []
    
    for r in reports:
        report_data = r.get('data', {})
        
        # Filter by status
        if status and r.get('status') != status:
            continue
            
        # Filter by employee
        if employee and report_data.get('employee') != employee:
            continue
            
        # Filter by server
        if server and server not in report_data.get('servers', []):
            continue
            
        # Filter by problem category
        if category:
            problems = report_data.get('problems', [])
            has_cat = any((p.get('category') == category or p.get('type') == category) for p in problems)
            if not has_cat:
                continue
                
        # Filter by dates
        created_at_str = r.get('created_at') or r.get('timestamp')
        if created_at_str:
            try:
                report_date = datetime.fromisoformat(created_at_str).date()
                if start_date:
                    start = datetime.fromisoformat(start_date).date()
                    if report_date < start:
                        continue
                if end_date:
                    end = datetime.fromisoformat(end_date).date()
                    if report_date > end:
                        continue
            except Exception:
                pass
                
        filtered_reports.append(r)
        
    # Sort reports newest first
    filtered_reports.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return filtered_reports

# 3c. Create a personal report
@app.post("/api/reports")
async def create_personal_report(payload: Dict[str, Any], user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    reports = read_reports()
    
    emp_name = user_name
    emp_data = {
        "name": user_name,
        "unit": (emp.get("unit") if isinstance(emp.get("unit"), str) else (emp.get("unit")[0] if emp and isinstance(emp.get("unit"), list) and emp.get("unit") else "Broadcast")) if emp else "Broadcast",
        "work_hours": emp.get("work_hours") if emp else "16:00 - 24:00",
        "special_conditions": emp.get("special_conditions") if emp else [],
        "work_location": emp.get("work_location") if emp else "Main Broadcasting Room"
    }

    report_id = str(uuid.uuid4())
    now_iso = datetime.now().isoformat()
    
    problems = payload.get("problems")
    if not isinstance(problems, list):
        problems = []
        if payload.get("description"):
            prob = {
                "type": payload.get("section", "General"),
                "category": payload.get("category", payload.get("section", "General")),
                "subcategory": payload.get("subcategory", "General"),
                "description": payload.get("description", ""),
            }
            if payload.get("live_event_name"):
                prob["live_event_name"] = payload.get("live_event_name")
                prob["live_event_source"] = payload.get("live_event_source", "Controls")
            problems.append(prob)

    # Validation: Employee can only report within their working Units
    data_en = read_employees(english=True)
    target_emp = next((e for e in data_en.get("employees", []) if (e.get("name") or "").strip().lower() == user_name.strip().lower()), None)
    if target_emp:
        authorized_units = get_employee_authorized_units(target_emp)
        for p in problems:
            p_cat = (p.get("category") or p.get("type") or "").strip().lower()
            if p_cat:
                is_auth = False
                for u in authorized_units:
                    if p_cat == u or p_cat in u or u in p_cat:
                        is_auth = True
                        break
                if not is_auth:
                    raise HTTPException(status_code=403, detail=f"Unauthorized category/unit: '{p_cat}' for employee '{user_name}'")

    period_val = payload.get("period") or datetime.now().strftime("%Y-%m-%d")
    new_report = {
        "id": report_id,
        "timestamp": now_iso,
        "created_at": now_iso,
        "updated_at": now_iso,
        "status": "pending",
        "data": {
            "employee": emp_name,
            "employee_id": emp.get("id") if emp else None,
            "employee_data": emp_data,
            "date": period_val,
            "period": period_val,
            "work_sections": payload.get("work_sections") or [payload.get("section", "General")],
            "servers": payload.get("servers", []),
            "problems": problems,
            "rating": payload.get("rating", 8),
            "mood": payload.get("mood", "😐 Normal"),
            "additional_info": payload.get("additional_info", "")
        }
    }
    
    reports.insert(0, new_report)
    if write_reports(reports):
        return {"message": "Report submitted successfully", "report": new_report}
    raise HTTPException(status_code=500, detail="Failed to save report to database")

def get_leader_sections(emp: dict) -> set:
    """Extracts lowercase section/category names associated with a leader."""
    sections = set()
    if not isinstance(emp, dict):
        return sections

    # 1. leader_type (e.g. "social leader" -> "social")
    l_type = emp.get("leader_type") or ""
    if l_type:
        l_clean = str(l_type).lower().replace("leader", "").strip()
        if l_clean:
            sections.add(l_clean)
            if "broadcast" in sections:
                sections.update(["broadcast", "helpdesk", "live", "playlist"])
            return sections

    # 2. roles (e.g. ["Social", "Leader"] -> "social")
    roles = emp.get("roles") or []
    if isinstance(roles, list):
        for r in roles:
            r_str = str(r).strip().lower()
            if r_str and r_str != "leader":
                sections.add(r_str)

    # 3. unit (e.g. ["Social"] or "Social" -> "social")
    unit = emp.get("unit") or []
    if isinstance(unit, str):
        unit = [unit]
    if isinstance(unit, list):
        for u in unit:
            u_str = str(u).strip().lower()
            for sec in ["social", "archive", "broadcast", "conductor", "live", "playlist", "helpdesk", "r&d"]:
                if sec in u_str:
                    sections.add(sec)

    # Broadcast leader manages helpdesk, live, and playlist sections
    if "broadcast" in sections:
        sections.update(["broadcast", "helpdesk", "live", "playlist"])

    return sections

# 3b. Pending Leader Reviews (Admin Only - Consolidated Leader Reports)
@app.get("/api/reports/pending-leader")
async def get_pending_leader_reports(user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    if role_tier != "Admin":
        raise HTTPException(status_code=403, detail="Access denied. Pending Leader Reviews are accessible only to Administrators.")

    reports = read_reports()
    pending = [r for r in reports if r.get('status') == 'pending']
    
    # Consolidated Leader Reports submitted via "Create Consolidated Leader Report"
    leader_pending = []
    for r in pending:
        is_cons = r.get('is_consolidated') or r.get('isConsolidated') or False
        if is_cons:
            leader_pending.append(r)
            
    return leader_pending

# 3c. Pending Personal Reviews (Admin & Designated Leaders - Personal Shift Reports)
@app.get("/api/reports/pending-personal")
async def get_pending_personal_reports(user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    if role_tier == "Employee":
        raise HTTPException(status_code=403, detail="Access denied. Employees do not have access to Pending Personal Reviews.")

    reports = read_reports()
    data_en = read_employees(english=True)

    pending = [r for r in reports if r.get('status') == 'pending']
    
    # Personal Reports are all non-consolidated reports (submitted via "Submit Personal Report")
    personal_pending = []
    for r in pending:
        is_cons = r.get('is_consolidated') or r.get('isConsolidated') or False
        if not is_cons:
            personal_pending.append(r)

    # Scoping for Leaders: include all reports of their subordinates where allowed units are not yet fully approved
    if role_tier == "Leader" and emp is not None:
        emp_list = data_en.get("employees", [])
        
        # Build leader categories
        leader_cats = set()
        roles = emp.get("roles") or []
        if not isinstance(roles, list):
            roles = [roles]
        units = emp.get("unit") or []
        if not isinstance(units, list):
            units = [units]
        l_type = str(emp.get("leader_type") or "").lower()
        valid_categories = {'broadcast', 'conductor', 'archive', 'social', 'r&d', 'live', 'playlist', 'helpdesk'}
        for r in roles:
            r_clean = str(r).strip().lower()
            if r_clean in valid_categories:
                leader_cats.add(r_clean)
        for u in units:
            u_clean = str(u).strip().lower()
            if "social" in u_clean:
                leader_cats.add("social")
            for cat in valid_categories:
                if cat in u_clean:
                    leader_cats.add(cat)
        for cat in valid_categories:
            if cat in l_type:
                leader_cats.add(cat)
                
        scoped_pending = []
        for r in personal_pending:
            if check_leader_report_access(emp, r, emp_list):
                r_data = r.get("data") or {}
                problems = r_data.get("problems") or r.get("problems") or []
                emp_name = (r_data.get("employee") or r.get("employee") or "").strip().lower()
                emp_id_str = str(r_data.get("employee_id") or r.get("employee_id") or "")
                target_emp = next((e for e in emp_list if (e.get("name") or "").strip().lower() == emp_name or str(e.get("id")) == emp_id_str), None)
                
                if target_emp:
                    emp_auth_units = get_employee_authorized_units(target_emp)
                    report_units = set()
                    for p in problems:
                        p_cat = (p.get("category") or p.get("type") or "").strip().lower()
                        if p_cat:
                            for u in emp_auth_units:
                                if p_cat == u or p_cat in u or u in p_cat:
                                    report_units.add(u)
                                    break
                    if not report_units:
                        report_units = emp_auth_units
                        
                    allowed_units = set()
                    for u in report_units:
                        is_match = False
                        for c in leader_cats:
                            if c == u or c in u or u in c:
                                is_match = True
                                break
                        if is_match:
                            allowed_units.add(u)
                            
                    approved_units = r.get("approved_units") or []
                    has_pending_unit = False
                    for u in allowed_units:
                        if u not in approved_units:
                            has_pending_unit = True
                            break
                            
                    if has_pending_unit:
                        scoped_pending.append(filter_report_for_leader(emp, r, emp_list))
        personal_pending = scoped_pending

    elif role_tier == "Admin":
        emp_list = data_en.get("employees", [])
        personal_pending = [r for r in personal_pending if is_report_pending_for_admin(r, emp_list)]

    return personal_pending

# Legacy fallback pending endpoint for backward compatibility
@app.get("/api/reports/pending")
async def get_pending_reports(user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    if role_tier == "Admin":
        return await get_pending_leader_reports(user_context)
    else:
        return await get_pending_personal_reports(user_context)

# 4. View report detail
@app.get("/api/reports/{report_id}")
async def get_report_details(report_id: str, user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    reports = read_reports()
    for r in reports:
        if r.get('id') == report_id:
            if role_tier == "Leader" and emp is not None:
                data_en = read_employees(english=True)
                emp_list = data_en.get("employees", [])
                if not check_leader_report_access(emp, r, emp_list):
                    raise HTTPException(status_code=403, detail="Unauthorized access to this report.")
                filtered_r = filter_report_for_leader(emp, r, emp_list)
            else:
                filtered_r = dict(r)
                
            data_en = read_employees(english=True)
            emp_list = data_en.get("employees", [])
            r_data = r.get("data") or {}
            problems = r_data.get("problems") or r.get("problems") or []
            
            emp_name = (r_data.get("employee") or r.get("employee") or "").strip().lower()
            emp_id_str = str(r_data.get("employee_id") or r.get("employee_id") or "")
            target_emp = next((e for e in emp_list if (e.get("name") or "").strip().lower() == emp_name or str(e.get("id")) == emp_id_str), None)
            
            allowed_units = []
            if target_emp:
                emp_auth_units = get_employee_authorized_units(target_emp)
                report_units = set()
                for p in problems:
                    p_cat = (p.get("category") or p.get("type") or "").strip().lower()
                    if p_cat:
                        for u in emp_auth_units:
                            if p_cat == u or p_cat in u or u in p_cat:
                                report_units.add(u)
                                break
                if not report_units:
                    report_units = emp_auth_units
                    
                if role_tier == "Admin" or user_name.strip().upper() == "RAL":
                    allowed_units = list(report_units)
                elif role_tier == "Leader" and emp is not None:
                    leader_cats = set()
                    roles = emp.get("roles") or []
                    if not isinstance(roles, list):
                        roles = [roles]
                    units = emp.get("unit") or []
                    if not isinstance(units, list):
                        units = [units]
                    l_type = str(emp.get("leader_type") or "").lower()
                    valid_categories = {'broadcast', 'conductor', 'archive', 'social', 'r&d', 'live', 'playlist', 'helpdesk'}
                    for roles_r in roles:
                        r_clean = str(roles_r).strip().lower()
                        if r_clean in valid_categories:
                            leader_cats.add(r_clean)
                    for units_u in units:
                        u_clean = str(units_u).strip().lower()
                        if "social" in u_clean:
                            leader_cats.add("social")
                        for cat in valid_categories:
                            if cat in u_clean:
                                leader_cats.add(cat)
                    for cat in valid_categories:
                        if cat in l_type:
                            leader_cats.add(cat)
                            
                    for u in report_units:
                        is_match = False
                        for c in leader_cats:
                            if c == u or c in u or u in c:
                                is_match = True
                                break
                        if is_match:
                            allowed_units.append(u)
                            
            filtered_r = dict(filtered_r)
            filtered_r["allowed_review_units"] = [u.capitalize() for u in allowed_units]
            filtered_r["approved_units"] = [u.capitalize() for u in (r.get("approved_units") or [])]
            return filtered_r
    raise HTTPException(status_code=404, detail="Report not found")

# 4b. Delete report (Admin only)
@app.delete("/api/reports/{report_id}")
async def delete_report(report_id: str, user_context: tuple = Depends(get_user_role_context)):
    """Permanently delete a report by ID (Admin only)"""
    user_name, role_tier, emp = user_context
    if role_tier != "Admin":
        raise HTTPException(status_code=403, detail="Access denied. Only Administrators can delete reports.")

    reports = read_reports()
    report_found = False
    new_reports = []

    for r in reports:
        if r.get('id') == report_id:
            report_found = True
        else:
            new_reports.append(r)

    if not report_found:
        raise HTTPException(status_code=404, detail="Report not found")

    if not write_reports(new_reports):
        raise HTTPException(status_code=500, detail="Failed to save changes to database")

    return {"message": "Report deleted successfully."}

# 4c. Edit/Update report (Admin only)
@app.put("/api/reports/{report_id}")
async def update_report(report_id: str, payload: ReportUpdateModel, user_context: tuple = Depends(get_user_role_context)):
    """Permanently update a report by ID (Admin only)"""
    user_name, role_tier, emp = user_context
    if role_tier != "Admin":
        raise HTTPException(status_code=403, detail="Access denied. Only Administrators can edit reports.")

    reports = read_reports()
    report_index = -1
    for idx, r in enumerate(reports):
        if r.get('id') == report_id:
            report_index = idx
            break

    if report_index == -1:
        raise HTTPException(status_code=404, detail="Report not found")

    report_entry = reports[report_index]
    
    # 1. Update dates and timestamps
    # ISO timestamp format: "YYYY-MM-DDTHH:MM:SS"
    new_timestamp = f"{payload.date}T{payload.time}:00"
    
    report_entry["timestamp"] = new_timestamp
    if "created_at" in report_entry:
        report_entry["created_at"] = new_timestamp
    if "submitted_at" in report_entry:
        report_entry["submitted_at"] = new_timestamp
    report_entry["updated_at"] = datetime.now().isoformat()
    
    # 2. Update status and leader fields
    report_entry["status"] = payload.status
    if payload.leader_name:
        report_entry["leader_name"] = payload.leader_name
    elif "leader_name" in report_entry:
        report_entry["leader_name"] = payload.employee

    # 3. Update data dict
    r_data = report_entry.get("data") or {}
    r_data["employee"] = payload.employee
    r_data["employee_id"] = payload.employee_id
    r_data["date"] = payload.date
    r_data["period"] = payload.date
    r_data["rating"] = payload.rating
    r_data["mood"] = payload.mood
    r_data["additional_info"] = payload.additional_info
    
    # Sync employee_data nested dict
    data_en = read_employees(english=True)
    target_emp = next((e for e in data_en.get("employees", []) if e.get("id") == payload.employee_id or (e.get("name") or "").strip().lower() == payload.employee.strip().lower()), None)
    
    # Validation: Verify that the employee is allowed to report for that Unit
    if target_emp:
        authorized_units = get_employee_authorized_units(target_emp)
        for p in payload.problems:
            p_cat = (p.get("category") or p.get("type") or "").strip().lower()
            if p_cat:
                is_auth = False
                for u in authorized_units:
                    if p_cat == u or p_cat in u or u in p_cat:
                        is_auth = True
                        break
                if not is_auth:
                    raise HTTPException(status_code=403, detail=f"Unauthorized category/unit: '{p_cat}' for employee '{payload.employee}'")

    if target_emp:
        r_data["employee_data"] = {
            "name": target_emp.get("name"),
            "unit": payload.unit,
            "work_hours": target_emp.get("work_hours"),
            "special_conditions": target_emp.get("special_conditions", []),
            "work_location": target_emp.get("work_location")
        }
    else:
        emp_data = r_data.get("employee_data") or {}
        emp_data["unit"] = payload.unit
        emp_data["name"] = payload.employee
        r_data["employee_data"] = emp_data

    # Update problems list
    r_data["problems"] = payload.problems
    if "problems" in report_entry:
        report_entry["problems"] = payload.problems
        
    report_entry["data"] = r_data

    # 4. Update manager feedback / approval info
    if payload.status == "approved" or payload.manager_rating is not None:
        report_entry["manager_rating"] = payload.manager_rating
        report_entry["manager_comment"] = payload.manager_comment
        report_entry["manager_feedback"] = {
            "rating": payload.manager_rating or 0,
            "comment": payload.manager_comment or "",
            "timestamp": report_entry.get("manager_feedback", {}).get("timestamp") or datetime.now().isoformat(),
            "manager_id": payload.leader_name or user_name,
            "manager_role": "Leader" if payload.leader_name else "Admin"
        }
    else:
        # If status changed back to pending, clear approval fields
        if "manager_rating" in report_entry:
            del report_entry["manager_rating"]
        if "manager_comment" in report_entry:
            del report_entry["manager_comment"]
        if "manager_feedback" in report_entry:
            del report_entry["manager_feedback"]

    reports[report_index] = report_entry

    if not write_reports(reports):
        raise HTTPException(status_code=500, detail="Failed to save report to JSON database")

    # Save to Excel database if approved
    if payload.status == "approved":
        try:
            r_data["id"] = report_entry["id"]
            save_to_excel(r_data)
        except Exception as e:
            logger.error(f"Error saving to Excel: {e}")

    return {"message": "Report updated successfully.", "report": report_entry}

# 5. Approve report
@app.post("/api/reports/{report_id}/approve")
async def approve_report(report_id: str, approval: ApprovalModel, user_context: tuple = Depends(get_user_role_context)):
    """Approve a pending report, add feedback, and save to Excel"""
    user_name, role_tier, emp = user_context
    reports = read_reports()
    report_entry = None
    report_index = -1
    
    for idx, r in enumerate(reports):
        if r.get('id') == report_id:
            report_entry = r
            report_index = idx
            break
            
    if not report_entry:
        raise HTTPException(status_code=404, detail="Report not found")
        
    # Scope using centralized visibility logic
    data_en = read_employees(english=True)
    emp_list = data_en.get("employees", [])
    vis = get_report_visibility_for_user(user_name, role_tier, emp, report_entry, emp_list)
    if vis is None:
        raise HTTPException(status_code=403, detail="Unauthorized to approve this report.")
        
    # Allow scoring even if already approved to support multiple leaders or rating updates
        
    # Get report data
    r_data = report_entry.get('data', {}) or {}
    problems = r_data.get("problems") or report_entry.get("problems") or []
    
    # Target employee profile
    emp_name = (r_data.get("employee") or report_entry.get("employee") or "").strip().lower()
    emp_id_str = str(r_data.get("employee_id") or report_entry.get("employee_id") or "")
    target_emp = next((e for e in emp_list if (e.get("name") or "").strip().lower() == emp_name or str(e.get("id")) == emp_id_str), None)
    if not target_emp:
        raise HTTPException(status_code=400, detail="Employee profile not found.")
        
    emp_auth_units = get_employee_authorized_units(target_emp)
    
    # Calculate which units are present in the report's problems and authorized for this employee
    report_units = set()
    for p in problems:
        p_cat = (p.get("category") or p.get("type") or "").strip().lower()
        if p_cat:
            for u in emp_auth_units:
                if p_cat == u or p_cat in u or u in p_cat:
                    report_units.add(u)
                    break
    if not report_units:
        # Clean shift: default to employee's authorized units
        report_units = emp_auth_units

    # Determine allowed units for the reviewer
    if role_tier == "Admin" or user_name.strip().upper() == "RAL":
        allowed_units = report_units
    else:
        # Leader: check matching categories
        leader_cats = set()
        roles = emp.get("roles") or []
        if not isinstance(roles, list):
            roles = [roles]
        units = emp.get("unit") or []
        if not isinstance(units, list):
            units = [units]
        l_type = str(emp.get("leader_type") or "").lower()
        valid_categories = {'broadcast', 'conductor', 'archive', 'social', 'r&d', 'live', 'playlist', 'helpdesk'}
        for r in roles:
            r_clean = str(r).strip().lower()
            if r_clean in valid_categories:
                leader_cats.add(r_clean)
        for u in units:
            u_clean = str(u).strip().lower()
            if "social" in u_clean:
                leader_cats.add("social")
            for cat in valid_categories:
                if cat in u_clean:
                    leader_cats.add(cat)
        for cat in valid_categories:
            if cat in l_type:
                leader_cats.add(cat)
                
        allowed_units = set()
        for u in report_units:
            is_match = False
            for c in leader_cats:
                if c == u or c in u or u in c:
                    is_match = True
                    break
            if is_match:
                allowed_units.add(u)

    # 2. Determine target unit for this approval
    target_unit = approval.unit
    if target_unit:
        target_unit_clean = target_unit.strip().lower()
        matched_unit = None
        for u in allowed_units:
            if target_unit_clean == u or target_unit_clean in u or u in target_unit_clean:
                matched_unit = u
                break
        if not matched_unit:
            raise HTTPException(status_code=403, detail=f"Unauthorized to score for unit '{target_unit}' in this report.")
        score_unit = matched_unit
    else:
        if len(allowed_units) == 1:
            score_unit = list(allowed_units)[0]
        elif len(allowed_units) > 1:
            raise HTTPException(status_code=400, detail="Report has multiple units. Please specify which unit you are scoring.")
        else:
            if role_tier == "Admin":
                score_unit = list(report_units)[0] if report_units else "general"
            else:
                raise HTTPException(status_code=403, detail="Unauthorized to score any unit in this report.")

    # 3. Save score entry
    if "leader_scores" not in report_entry:
        report_entry["leader_scores"] = []
    
    score_entry = {
        "unit": score_unit,
        "leader_id": str(emp.get("id")) if emp else user_name,
        "leader_name": user_name,
        "score": approval.manager_rating,
        "comment": approval.manager_comment,
        "timestamp": datetime.now().isoformat()
    }
    
    existing_idx = -1
    for s_idx, s in enumerate(report_entry["leader_scores"]):
        if s.get("unit") == score_unit and s.get("leader_name").lower() == user_name.lower():
            existing_idx = s_idx
            break
            
    if existing_idx != -1:
        report_entry["leader_scores"][existing_idx] = score_entry
    else:
        report_entry["leader_scores"].append(score_entry)
        
    if "approved_units" not in report_entry:
        report_entry["approved_units"] = []
    if score_unit not in report_entry["approved_units"]:
        report_entry["approved_units"].append(score_unit)

    # 4. Check if report is fully approved
    is_fully_approved = True
    for u in report_units:
        if u not in report_entry["approved_units"]:
            is_fully_approved = False
            break
            
    if is_fully_approved:
        report_entry['status'] = 'approved'
        all_scores = [s["score"] for s in report_entry["leader_scores"]]
        avg_legacy = round(sum(all_scores) / len(all_scores)) if all_scores else approval.manager_rating
        report_entry['manager_rating'] = avg_legacy
        report_entry['manager_comment'] = approval.manager_comment
        report_entry['updated_at'] = datetime.now().isoformat()
        
        report_entry['manager_feedback'] = {
            'rating': avg_legacy,
            'comment': approval.manager_comment,
            'timestamp': datetime.now().isoformat(),
            'manager_id': user_name,
            'manager_role': role_tier
        }
        
        r_data['manager_rating'] = avg_legacy
        r_data['manager_comment'] = approval.manager_comment
    else:
        report_entry['status'] = 'pending'
        report_entry['updated_at'] = datetime.now().isoformat()

    # Standardize problem structures for excel handler (replicating report.py)
    if 'problems' in report_entry and 'problems' not in r_data:
        r_data['problems'] = report_entry['problems']
        
    if 'problems' in r_data:
        for i, problem in enumerate(r_data['problems']):
            if 'category' not in problem and 'type' in problem:
                problem['category'] = problem['type']
            if 'subcategory' not in problem and 'subtype' in problem:
                problem['subcategory'] = problem['subtype']
                
            # Inject live event info if needed
            is_live_event = problem.get('type') in ['Live Event', 'Live events']
            if is_live_event and ('live_event_name' not in problem or 'live_event_source' not in problem):
                live_event = r_data.get('live_events', {}).get(str(i), {})
                if live_event:
                    problem['live_event_name'] = live_event.get('name', 'Unspecified')
                    problem['live_event_source'] = live_event.get('source', 'Unspecified')
                    
    # Write back report data changes
    report_entry['data'] = r_data
    
    # Save JSON database
    if not write_reports(reports):
        raise HTTPException(status_code=500, detail="Failed to save report to JSON database")
        
    # Save to Excel database if fully approved
    if is_fully_approved:
        try:
            r_data["id"] = report_entry["id"]
            save_to_excel(r_data)
        except Exception as e:
            logger.error(f"Error saving to Excel: {e}")
            
    return {"message": "Report approved successfully", "report": report_entry}

# 5c. Get Detailed Employee Performance & Mood Statistics
@app.get("/api/employees/{emp_id_or_name}/stats")
async def get_employee_stats(emp_id_or_name: str, user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    if role_tier not in ["Admin", "Leader"]:
        raise HTTPException(status_code=403, detail="Access denied. Employee statistics accessible only to Administrators and Leaders.")

    employees_data = read_employees(english=True)
    employees = employees_data.get("employees", [])

    # Find target employee
    target_emp = None
    target_id_str = str(emp_id_or_name).strip().lower()
    for e in employees:
        if str(e.get("id")).lower() == target_id_str or (e.get("name") or "").strip().lower() == target_id_str:
            target_emp = e
            break

    if not target_emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    if role_tier == "Leader" and emp is not None:
        leader_id = str(emp.get("id"))
        leader_name = (emp.get("name") or "").strip().lower()

        rep_to = target_emp.get("reportsTo") or target_emp.get("reports_to") or []
        is_subordinate = False
        if isinstance(rep_to, list):
            if any(str(x).strip() == leader_id for x in rep_to if x is not None):
                is_subordinate = True
        elif rep_to is not None:
            if str(rep_to).strip() == leader_id or str(rep_to).strip().lower() == leader_name:
                is_subordinate = True

        if not is_subordinate:
            raise HTTPException(status_code=403, detail="Access denied. You can only view statistics of your subordinates.")

    target_id = str(target_emp.get("id"))
    target_name = (target_emp.get("name") or "").strip().lower()

    reports = read_reports()
    emp_reports = []

    for r in reports:
        r_data = r.get("data") or {}
        e_name = (r_data.get("employee") or r.get("employee") or r.get("leader_name") or "").strip().lower()
        e_id = str(r_data.get("employee_id") or r.get("employee_id") or "")

        if e_name == target_name or (e_id and e_id == target_id):
            emp_reports.append(r)

    total_reports_count = len(emp_reports)
    self_ratings = []
    leader_ratings = []
    admin_ratings = []
    mood_counts = {}

    history = []

    for r in emp_reports:
        r_data = r.get("data") or {}
        date_str = r.get("submitted_at") or r.get("created_at") or r.get("timestamp") or "-"

        # 1. Self Rating
        self_r = r_data.get("rating") or r.get("rating") or r.get("self_rating")
        self_val = None
        if self_r is not None:
            try:
                self_val = float(self_r)
                if 1 <= self_val <= 10:
                    self_ratings.append(self_val)
            except (ValueError, TypeError):
                self_val = None

        # 2. Manager Rating (Leader vs Admin)
        mgr_r = r.get("manager_rating") or (r.get("manager_feedback") or {}).get("rating") or r_data.get("manager_rating")
        mgr_feedback = r.get("manager_feedback") or {}
        mgr_id = (mgr_feedback.get("manager_id") or "").strip().upper()
        mgr_role = (mgr_feedback.get("manager_role") or "").strip()

        leader_val = None
        admin_val = None

        if mgr_r is not None:
            try:
                val = float(mgr_r)
                if 1 <= val <= 10:
                    if mgr_role == "Admin" or mgr_id in ["RAL", "ADMIN"]:
                        admin_ratings.append(val)
                        admin_val = val
                    else:
                        leader_ratings.append(val)
                        leader_val = val
            except (ValueError, TypeError):
                pass

        # 3. Mood State
        raw_mood = r_data.get("mood") or r.get("mood")
        mood_str = normalize_mood(raw_mood)
        mood_counts[mood_str] = mood_counts.get(mood_str, 0) + 1

        history.append({
            "date": date_str,
            "self_rating": self_val,
            "leader_rating": leader_val,
            "admin_rating": admin_val,
            "mood": mood_str
        })

    # Sort history newest first
    history.sort(key=lambda x: x["date"], reverse=True)

    avg_self = round(sum(self_ratings) / len(self_ratings), 2) if self_ratings else None
    avg_leader = round(sum(leader_ratings) / len(leader_ratings), 2) if leader_ratings else None
    avg_admin = round(sum(admin_ratings) / len(admin_ratings), 2) if admin_ratings else None

    # Calculate dominant mood
    dominant_mood = "Not recorded"
    if mood_counts:
        dominant_mood = max(mood_counts, key=mood_counts.get)

    # Calculate unit-specific performances based strictly on leader_scores
    unit_perf = []
    emp_units = get_employee_authorized_units(target_emp)
    for u in emp_units:
        scores_for_unit = []
        for r in emp_reports:
            scores = get_report_leader_scores(r, employees)
            rep_unit_scores = [s["score"] for s in scores if s.get("unit") == u]
            if rep_unit_scores:
                scores_for_unit.append(sum(rep_unit_scores) / len(rep_unit_scores))
        if scores_for_unit:
            avg_u = round(sum(scores_for_unit) / len(scores_for_unit), 2)
            unit_perf.append({
                "unit": u.capitalize(),
                "performance": avg_u
            })

    return {
        "employee_id": target_emp.get("id"),
        "employee_name": target_emp.get("name"),
        "unit": target_emp.get("unit"),
        "roles": target_emp.get("roles"),
        "total_reports_count": total_reports_count,
        "avg_self_rating": avg_self,
        "avg_leader_rating": avg_leader,
        "avg_admin_rating": avg_admin,
        "dominant_mood": dominant_mood,
        "history": history[:15],
        "unit_performances": unit_perf
    }

# 5b. Get Employee Performance Analytics (Ratings & Activity in Past Month)
@app.get("/api/analytics/employee-performance")
async def get_employee_performance_analytics(user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    if role_tier not in ["Admin", "Leader"]:
        raise HTTPException(status_code=403, detail="Access denied. Analytics accessible to Administrators and Leaders.")

    reports = read_reports()
    employees_data = read_employees(english=True)
    employees = employees_data.get("employees", [])

    # Filter past month cutoff (30 days ago)
    now = datetime.now()
    month_cutoff = now - timedelta(days=30)

    stats_by_emp = {}

    # Initialize stats dictionary for all employees
    for e in employees:
        e_id = str(e.get("id"))
        e_name = e.get("name") or "Unknown"
        unit_val = e.get("unit") or []
        unit_str = ", ".join(unit_val) if isinstance(unit_val, list) else str(unit_val)
        roles_val = e.get("roles") or []
        roles_str = ", ".join(roles_val) if isinstance(roles_val, list) else str(roles_val)

        stats_by_emp[e_name.strip().lower()] = {
            "employee_id": e_id,
            "employee_name": e_name,
            "unit": unit_str or "-",
            "roles": roles_str or "-",
            "past_month_reports_count": 0,
            "self_ratings": [],
            "manager_ratings": []
        }

    # Aggregate metrics from reports
    for r in reports:
        date_str = r.get("submitted_at") or r.get("created_at") or r.get("timestamp") or ""
        r_date = None
        if date_str:
            try:
                clean_str = str(date_str).replace("Z", "+00:00").split("+")[0].split(".")[0]
                r_date = datetime.fromisoformat(clean_str)
            except Exception:
                pass
        
        is_past_month = False
        if r_date and r_date >= month_cutoff:
            is_past_month = True

        r_data = r.get("data") or {}
        emp_name = (r_data.get("employee") or r.get("employee") or r.get("leader_name") or "").strip().lower()

        if not emp_name:
            continue

        if emp_name not in stats_by_emp:
            stats_by_emp[emp_name] = {
                "employee_id": str(r_data.get("employee_id") or r.get("employee_id") or "-"),
                "employee_name": r_data.get("employee") or r.get("employee") or emp_name.upper(),
                "unit": "-",
                "roles": "-",
                "past_month_reports_count": 0,
                "self_ratings": [],
                "manager_ratings": []
            }

        # If report submitted in past month, increment count
        if is_past_month:
            stats_by_emp[emp_name]["past_month_reports_count"] += 1

        # Collect self rating (1-10)
        self_r = r_data.get("rating") or r.get("rating") or r.get("self_rating")
        if self_r is not None:
            try:
                val = float(self_r)
                if 1 <= val <= 10:
                    stats_by_emp[emp_name]["self_ratings"].append(val)
            except (ValueError, TypeError):
                pass

        # Collect manager / leader / admin rating (1-10)
        mgr_r = r.get("manager_rating") or (r.get("manager_feedback") or {}).get("rating")
        if mgr_r is not None:
            try:
                val = float(mgr_r)
                if 1 <= val <= 10:
                    stats_by_emp[emp_name]["manager_ratings"].append(val)
            except (ValueError, TypeError):
                pass

    # Compute averages
    result_list = []
    for key, item in stats_by_emp.items():
        self_list = item["self_ratings"]
        mgr_list = item["manager_ratings"]

        avg_self = round(sum(self_list) / len(self_list), 2) if self_list else None
        avg_mgr = round(sum(mgr_list) / len(mgr_list), 2) if mgr_list else None

        if avg_self is not None and avg_mgr is not None:
            combined_avg = round((avg_self + avg_mgr) / 2.0, 2)
        elif avg_self is not None:
            combined_avg = avg_self
        elif avg_mgr is not None:
            combined_avg = avg_mgr
        else:
            combined_avg = None

        result_list.append({
            "employee_id": item["employee_id"],
            "employee_name": item["employee_name"],
            "unit": item["unit"],
            "roles": item["roles"],
            "past_month_reports_count": item["past_month_reports_count"],
            "avg_self_rating": avg_self,
            "avg_manager_rating": avg_mgr,
            "combined_avg_rating": combined_avg
        })

    # Sort by past_month_reports_count desc, then combined_avg_rating desc
    result_list.sort(key=lambda x: (x["past_month_reports_count"], x["combined_avg_rating"] or 0), reverse=True)

    return {
        "period": "Last 30 Days",
        "employees": result_list
    }

# 6. Get list of employees and metadata configuration
@app.get("/api/employees")
async def get_employees():
    """Retrieve list of employees and dynamic settings"""
    return read_employees(english=True)

# Reassign Request Model
class ReassignModel(BaseModel):
    employee_id: int
    supervisor_id: Optional[int] = None

class ConsolidatedReportModel(BaseModel):
    leader_name: str
    period: str
    summary_notes: Optional[str] = ""
    included_report_ids: List[Any]
    has_issue: Optional[str] = "no"
    section: Optional[str] = "General"
    category: Optional[str] = "General"
    description: Optional[str] = ""
    live_event_name: Optional[str] = None
    live_event_source: Optional[str] = None

# 7. Add employee (Admin only)
@app.post("/api/employees")
async def add_employee(employee: EmployeeModel, user_context: tuple = Depends(get_user_role_context)):
    """Add a new employee to the database"""
    user_name, role_tier, emp = user_context
    if role_tier != "Admin":
        raise HTTPException(status_code=403, detail="Administrator access required to add employees.")

    data_en = read_employees(english=True)
    data_fa = read_employees(english=False)
    
    # Check if employee already exists in English db
    for emp in data_en.get('employees', []):
        if emp.get('name').lower() == employee.name.lower():
            raise HTTPException(status_code=400, detail="Employee already exists")

    existing_ids = [e.get('id', 0) for e in data_en.get('employees', []) if e.get('id') is not None]
    new_id = (max(existing_ids) + 1) if existing_ids else 1

    reports_list = []
    if employee.reportsTo is not None:
        if isinstance(employee.reportsTo, list):
            reports_list = [int(x) for x in employee.reportsTo if x is not None]
        else:
            reports_list = [int(employee.reportsTo)]

    if new_id in reports_list:
        raise HTTPException(status_code=400, detail="An employee cannot report to themselves")
    if check_reporting_cycle(data_en.get('employees', []), new_id, reports_list):
        raise HTTPException(status_code=400, detail="Circular reporting chain detected! Employee cannot report to a supervisor in their downstream chain.")

    # Construct English entry
    new_emp_en = {
        "id": new_id,
        "name": employee.name,
        "unit": employee.unit,
        "roles": employee.roles,
        "leader_type": employee.leader_type,
        "leader_shift": employee.leader_shift,
        "work_hours": employee.work_hours,
        "special_conditions": employee.special_conditions,
        "work_location": employee.work_location,
        "reportsTo": reports_list
    }
    
    # Construct Persian entry
    fa_location = "کار در منزل" if "home" in employee.work_location.lower() else "دفتر مرکزی"
    fa_units = []
    for u in employee.unit:
        u_lower = u.lower()
        if "archive" in u_lower:
            fa_units.append("آرشیو")
        elif "conductor" in u_lower:
            fa_units.append("کنداکتور")
        elif "social" in u_lower:
            fa_units.append("شبکه‌های اجتماعی")
        elif "broadcast" in u_lower:
            fa_units.append("پخش")
        else:
            fa_units.append(u)
            
    fa_roles = []
    for r in employee.roles:
        r_lower = r.lower()
        if "live" in r_lower:
            fa_roles.append("لایو")
        elif "playlist" in r_lower:
            fa_roles.append("پلی‌لیست")
        elif "helpdesk" in r_lower:
            fa_roles.append("پشتیبانی فنی")
        elif "social" in r_lower:
            fa_roles.append("شبکه‌های اجتماعی")
        elif "conductor" in r_lower:
            fa_roles.append("کنداکتور")
        elif "r&d" in r_lower or "research" in r_lower:
            fa_roles.append("تحقیق و توسعه")
        elif "leader" in r_lower:
            fa_roles.append("سرپرست")
        else:
            fa_roles.append(r)
            
    fa_shift = employee.leader_shift
        
    new_emp_fa = {
        "id": new_id,
        "name": employee.name,
        "unit": fa_units,
        "roles": fa_roles,
        "leader_type": employee.leader_type,
        "leader_shift": fa_shift,
        "work_hours": employee.work_hours,
        "special_conditions": employee.special_conditions,
        "work_location": fa_location,
        "reportsTo": reports_list
    }
    
    data_en.setdefault('employees', []).append(new_emp_en)
    data_fa.setdefault('employees', []).append(new_emp_fa)
    
    if write_employees(data_en, english=True) and write_employees(data_fa, english=False):
        return {"message": "Employee added successfully", "employee": new_emp_en}
    raise HTTPException(status_code=500, detail="Failed to save employee changes")

# 8. Edit employee (Admin only)
@app.put("/api/employees/{name}")
async def edit_employee(name: str, employee: EmployeeModel, user_context: tuple = Depends(get_user_role_context)):
    """Edit existing employee details"""
    user_name, role_tier, emp = user_context
    if role_tier != "Admin":
        raise HTTPException(status_code=403, detail="Administrator access required to edit employees.")

    data_en = read_employees(english=True)
    data_fa = read_employees(english=False)
    
    # Find employee ID
    target_id = None
    for emp_item in data_en.get('employees', []):
        if emp_item.get('name').lower() == name.lower() or str(emp_item.get('id')) == name:
            target_id = emp_item.get('id')
            break

    reports_list = []
    if employee.reportsTo is not None:
        if isinstance(employee.reportsTo, list):
            reports_list = [int(x) for x in employee.reportsTo if x is not None]
        else:
            reports_list = [int(employee.reportsTo)]

    if target_id is not None:
        if target_id in reports_list:
            raise HTTPException(status_code=400, detail="An employee cannot report to themselves")
        if check_reporting_cycle(data_en.get('employees', []), target_id, reports_list):
            raise HTTPException(status_code=400, detail="Circular reporting chain detected! Employee cannot report to a supervisor in their downstream chain.")

    found_en = False
    for emp_item in data_en.get('employees', []):
        if emp_item.get('name').lower() == name.lower() or str(emp_item.get('id')) == name:
            emp_item.update({
                "name": employee.name,
                "unit": employee.unit,
                "roles": employee.roles,
                "leader_type": employee.leader_type,
                "leader_shift": employee.leader_shift,
                "work_hours": employee.work_hours,
                "special_conditions": employee.special_conditions,
                "work_location": employee.work_location,
                "reportsTo": reports_list
            })
            found_en = True
            break
            
    if not found_en:
        raise HTTPException(status_code=404, detail="Employee not found")
        
    # Also update in Persian database
    for emp_item in data_fa.get('employees', []):
        if emp_item.get('name').lower() == name.lower() or str(emp_item.get('id')) == name:
            fa_location = "کار در منزل" if "home" in employee.work_location.lower() else "دفتر مرکزی"
            fa_units = []
            for u in employee.unit:
                u_lower = u.lower()
                if "archive" in u_lower:
                    fa_units.append("آرشیو")
                elif "conductor" in u_lower:
                    fa_units.append("کنداکتور")
                elif "social" in u_lower:
                    fa_units.append("شبکه‌های اجتماعی")
                elif "broadcast" in u_lower:
                    fa_units.append("پخش")
                else:
                    fa_units.append(u)
            
            fa_roles = []
            for r in employee.roles:
                r_lower = r.lower()
                if "live" in r_lower:
                    fa_roles.append("لایو")
                elif "playlist" in r_lower:
                    fa_roles.append("پلی‌لیست")
                elif "helpdesk" in r_lower:
                    fa_roles.append("پشتیبانی فنی")
                elif "social" in r_lower:
                    fa_roles.append("شبکه‌های اجتماعی")
                elif "conductor" in r_lower:
                    fa_roles.append("کنداکتور")
                elif "r&d" in r_lower or "research" in r_lower:
                    fa_roles.append("تحقیق و توسعه")
                elif "leader" in r_lower:
                    fa_roles.append("سرپرست")
                else:
                    fa_roles.append(r)
            
            fa_shift = employee.leader_shift
                    
            emp_item.update({
                "name": employee.name,
                "unit": fa_units,
                "roles": fa_roles,
                "leader_type": employee.leader_type,
                "leader_shift": fa_shift,
                "work_hours": employee.work_hours,
                "special_conditions": employee.special_conditions,
                "work_location": fa_location,
                "reportsTo": reports_list
            })
            break
            
    if write_employees(data_en, english=True) and write_employees(data_fa, english=False):
        return {"message": "Employee updated successfully", "employee": employee}
    raise HTTPException(status_code=500, detail="Failed to save employee changes")

# 9. Reassign Employee (Admin only)
@app.post("/api/employees/reassign")
async def reassign_employee(req: ReassignModel, user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    if role_tier != "Admin":
        raise HTTPException(status_code=403, detail="Administrator access required to reassign employees.")

    data_en = read_employees(english=True)
    data_fa = read_employees(english=False)
    
    emp_id = req.employee_id
    sup_id = req.supervisor_id
    
    if sup_id is not None:
        if sup_id == emp_id:
            raise HTTPException(status_code=400, detail="An employee cannot report to themselves")
        if check_reporting_cycle(data_en.get('employees', []), emp_id, sup_id):
            raise HTTPException(status_code=400, detail="Circular reporting chain detected!")
            
    found = False
    for emp_item in data_en.get('employees', []):
        if emp_item.get('id') == emp_id:
            emp_item['reportsTo'] = [sup_id] if sup_id is not None else []
            found = True
            break
            
    for emp_item in data_fa.get('employees', []):
        if emp_item.get('id') == emp_id:
            emp_item['reportsTo'] = [sup_id] if sup_id is not None else []
            break
            
    if not found:
        raise HTTPException(status_code=404, detail="Employee not found")
        
    if write_employees(data_en, english=True) and write_employees(data_fa, english=False):
        return {"message": "Employee reassigned successfully", "employee_id": emp_id, "supervisor_id": sup_id}
    raise HTTPException(status_code=500, detail="Failed to save reassignment")

# 10. Submit Consolidated Leader Report (Leader or Admin)
@app.post("/api/reports/consolidated")
async def submit_consolidated_report(report: ConsolidatedReportModel, user_context: tuple = Depends(get_user_role_context)):
    user_name, role_tier, emp = user_context
    if role_tier == "Employee":
        raise HTTPException(status_code=403, detail="Employees are not authorized to create consolidated leader reports.")

    reports = read_reports()
    report_id = str(uuid.uuid4())
    now_iso = datetime.now().isoformat()
    
    problems = []
    if report.has_issue == "yes" and report.description:
        prob = {
            "type": report.section or "General",
            "category": report.category or "General",
            "subcategory": "General",
            "description": report.description,
        }
        if report.live_event_name:
            prob["live_event_name"] = report.live_event_name
            prob["live_event_source"] = report.live_event_source or "Controls"
        problems.append(prob)

    emp_data = {
        "name": report.leader_name,
        "unit": "Leader Supervision",
        "work_hours": "Leader Shift",
        "special_conditions": ["Leader"],
        "work_location": "Main Control Room"
    }

    entry = {
        "id": report_id,
        "is_consolidated": True,
        "leader_name": report.leader_name,
        "period": report.period,
        "summary_notes": report.summary_notes,
        "included_report_ids": report.included_report_ids,
        "timestamp": now_iso,
        "created_at": now_iso,
        "updated_at": now_iso,
        "status": "pending",
        "data": {
            "employee": report.leader_name,
            "employee_id": emp.get("id") if emp else None,
            "employee_data": emp_data,
            "date": report.period,
            "period": report.period,
            "work_sections": [report.section if report.has_issue == "yes" else "General"],
            "problems": problems,
            "rating": 8,
            "mood": "😐 Normal",
            "additional_info": report.summary_notes,
            "included_report_ids": report.included_report_ids
        }
    }
    
    reports.insert(0, entry)
    if write_reports(reports):
        return {"message": "Consolidated report submitted successfully", "report": entry}
    raise HTTPException(status_code=500, detail="Failed to save consolidated report")

# 11. Delete employee (Admin only)
@app.delete("/api/employees/{name_or_id}")
async def delete_employee(name_or_id: str, user_context: tuple = Depends(get_user_role_context)):
    """Delete an employee from the database by name or ID"""
    user_name, role_tier, emp = user_context
    if role_tier != "Admin":
        raise HTTPException(status_code=403, detail="Administrator access required to delete employees.")

    data_en = read_employees(english=True)
    data_fa = read_employees(english=False)
    
    employees_en = data_en.get('employees', [])
    employees_fa = data_fa.get('employees', [])
    
    is_id = name_or_id.isdigit()
    target_id = int(name_or_id) if is_id else None
    target_name_clean = name_or_id.strip().lower()
    
    new_employees_en = []
    found_en = False
    for e in employees_en:
        e_name = (e.get('name') or "").strip().lower()
        e_id = e.get('id')
        if (target_id is not None and e_id == target_id) or (e_name == target_name_clean):
            found_en = True
        else:
            new_employees_en.append(e)
            
    new_employees_fa = []
    found_fa = False
    for e in employees_fa:
        e_name = (e.get('name') or "").strip().lower()
        e_id = e.get('id')
        if (target_id is not None and e_id == target_id) or (e_name == target_name_clean):
            found_fa = True
        else:
            new_employees_fa.append(e)
            
    if not found_en and not found_fa:
        raise HTTPException(status_code=404, detail="Employee not found")
        
    data_en['employees'] = new_employees_en
    data_fa['employees'] = new_employees_fa
    
    if write_employees(data_en, english=True) and write_employees(data_fa, english=False):
        return {"message": "Employee deleted successfully"}
    raise HTTPException(status_code=500, detail="Failed to delete employee")

# 10. Update weight configuration (in employees_en.json / employees.json)
@app.post("/api/employees/config")
async def save_employee_configs(config_data: Dict[str, Any]):
    """Update settings configs like error_weights, decision_thresholds, error_categories in employees databases"""
    data_en = read_employees(english=True)
    data_fa = read_employees(english=False)
    
    # Update config keys
    config_keys = [
        "error_weights", "decision_thresholds", "error_categories", 
        "work_location_weights", "special_condition_weights", "experience_level_weights",
        "units", "roles", "special_conditions"
    ]
    
    for key in config_keys:
        if key in config_data:
            data_en[key] = config_data[key]
            data_fa[key] = config_data[key]
            
    if write_employees(data_en, english=True) and write_employees(data_fa, english=False):
        return {"message": "Configurations updated successfully", "config": config_data}
    raise HTTPException(status_code=500, detail="Failed to save configurations")

# 11. Document downloader
@app.get("/api/documents")
async def get_document(path: str):
    """Download/view uploaded report documents safely"""
    # Prevent directory traversal by resolving path
    bot_dir = Path(__file__).resolve().parent / 'Report Bot'
    file_path = (bot_dir / path).resolve()
    
    # Ensure the path is within the bot directory
    if not file_path.is_relative_to(bot_dir):
        raise HTTPException(status_code=403, detail="Access denied")
        
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(file_path)

# Serve static files for frontend SPA
# Ensure static folder exists
static_dir = Path(__file__).resolve().parent / 'static'
static_dir.mkdir(exist_ok=True)
(static_dir / 'css').mkdir(exist_ok=True)
(static_dir / 'js').mkdir(exist_ok=True)

# Mount static folder
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=3006, reload=True)
