from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import sqlite3
import uuid
import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import qrcode
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template, request,
    send_file, send_from_directory, session, url_for
)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = Path(__file__).resolve().parent
configured_data_dir = Path(os.environ.get("DATA_DIR", "/var/data" if (os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER")) else str(BASE_DIR / "instance")))
try:
    configured_data_dir.mkdir(parents=True, exist_ok=True)
    DATA_DIR = configured_data_dir
except OSError as exc:
    # Avoid failing the whole web service if a Render disk path is configured before
    # a disk is mounted. This fallback is ephemeral; see README for production setup.
    DATA_DIR = BASE_DIR / "instance"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"WARNING: Could not use DATA_DIR={configured_data_dir}: {exc}. Using {DATA_DIR}; add a persistent Render disk.")

DB_PATH = DATA_DIR / "patamahali.sqlite3"
BACKUP_DIR = DATA_DIR / "backups"
LISTING_UPLOAD_DIR = DATA_DIR / "uploads" / "listings"
PRIVATE_DOC_DIR = DATA_DIR / "private_documents"
for directory in (BACKUP_DIR, LISTING_UPLOAD_DIR, PRIVATE_DOC_DIR):
    directory.mkdir(parents=True, exist_ok=True)

ADMIN_PATH = "promise212324"  # Fixed private admin entry; do not configure through Render variables.
ADMIN_ROOT = "/" + ADMIN_PATH
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", str(12 * 1024 * 1024)))
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_DOC_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
)


def load_secret_key() -> str:
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = DATA_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    key_file.write_text(value, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return value


app.secret_key = load_secret_key()

DEFAULT_SETTINGS = {
    "site_name": "PataMahali",
    "tagline": "Find the right place.",
    "site_description": "Find verified homes, stays, shops, warehouses and property with clearer information and accountable listings.",
    "brand_primary": "#176B4D",
    "brand_accent": "#D9A441",
    "management_url": "",
    "support_phone": "",
    "support_email": "",
    "social_instagram_enabled": "0", "social_instagram_url": "",
    "social_facebook_enabled": "0", "social_facebook_url": "",
    "social_tiktok_enabled": "0", "social_tiktok_url": "",
    "social_youtube_enabled": "0", "social_youtube_url": "",
    "social_linkedin_enabled": "0", "social_linkedin_url": "",
    "social_x_enabled": "0", "social_x_url": "",
    "payment_method": "M-Pesa",
    "payment_paybill": "",
    "payment_account": "",
    "payment_phone": "",
    "payment_instructions": "Pay the listing fee using the verified details below, then enter your payment reference. Your listing stays private until the payment and property checks are approved.",
    "fee_residential": "500",
    "fee_short_stay": "700",
    "fee_commercial": "1000",
    "fee_industrial": "1500",
    "fee_land_sale": "1000",
    "fee_property_sale": "1000",
    "fee_featured": "300",
    "listing_expiry_days": "14",
    "public_base_url": os.environ.get("PUBLIC_BASE_URL", ""),
    "terms_notice": "Never pay a deposit before independently confirming the property and the person receiving payment.",
}

CATEGORY_META = {
    "residential": {"label": "Homes & rentals", "short": "Homes", "description": "Bedsitters, studios, apartments and family homes.", "fee": "fee_residential", "types": ["Bedsitter", "Studio", "1-bedroom apartment", "2-bedroom apartment", "3+ bedroom house", "Maisonette", "Townhouse", "Furnished apartment", "Other home"]},
    "short_stay": {"label": "Hotels & short stays", "short": "Stays", "description": "Hotels, BnBs, guest houses and furnished stays.", "fee": "fee_short_stay", "types": ["Hotel room", "BnB", "Guest house", "Holiday home", "Serviced apartment", "Other stay"]},
    "commercial": {"label": "Shops & business premises", "short": "Shops & offices", "description": "Shops, stalls, offices and business premises.", "fee": "fee_commercial", "types": ["Shop", "Stall", "Office", "Showroom", "Restaurant space", "Workshop", "Other commercial space"]},
    "industrial": {"label": "Warehouses & industrial", "short": "Warehouses", "description": "Godowns, warehouses, yards and logistics space.", "fee": "fee_industrial", "types": ["Warehouse / godown", "Storage unit", "Industrial yard", "Workshop", "Logistics facility", "Other industrial space"]},
    "land_sale": {"label": "Land & plots", "short": "Land", "description": "Plots and land listings with location and terms.", "fee": "fee_land_sale", "types": ["Residential plot", "Agricultural land", "Commercial plot", "Industrial land", "Other land"]},
    "property_sale": {"label": "Property for sale", "short": "For sale", "description": "Homes, buildings and investment property for sale.", "fee": "fee_property_sale", "types": ["House for sale", "Apartment for sale", "Commercial building", "Apartment block", "Mixed-use property", "Other property"]},
}
PRICE_PERIODS = ["per month", "per night", "per day", "per year", "total price", "per square foot"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL DEFAULT 'seeker',
    account_type TEXT NOT NULL DEFAULT 'seeker',
    full_name TEXT NOT NULL,
    business_name TEXT NOT NULL DEFAULT '',
    email TEXT UNIQUE,
    phone TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    identity_type TEXT NOT NULL DEFAULT 'national_id',
    identity_front TEXT NOT NULL DEFAULT '',
    identity_back TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0,
    suspended INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    property_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_amount REAL NOT NULL DEFAULT 0,
    price_period TEXT NOT NULL DEFAULT 'per month',
    deposit_amount REAL,
    bedrooms INTEGER,
    bathrooms INTEGER,
    floor_area TEXT NOT NULL DEFAULT '',
    amenities TEXT NOT NULL DEFAULT '',
    location_name TEXT NOT NULL,
    landmarks TEXT NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL,
    property_condition TEXT NOT NULL DEFAULT '',
    images TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    approval_status TEXT NOT NULL DEFAULT 'pending',
    payment_status TEXT NOT NULL DEFAULT 'pending',
    payment_reference TEXT NOT NULL DEFAULT '',
    fee_amount REAL NOT NULL DEFAULT 0,
    property_verified INTEGER NOT NULL DEFAULT 0,
    featured_until TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_confirmed_at TEXT NOT NULL DEFAULT '',
    views INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(owner_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS interests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    seeker_id INTEGER,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    FOREIGN KEY(listing_id) REFERENCES listings(id)
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    reporter_id INTEGER,
    reporter_name TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(listing_id) REFERENCES listings(id)
);
CREATE TABLE IF NOT EXISTS visitor_sessions (
    visitor_key TEXT PRIMARY KEY,
    user_id INTEGER,
    role TEXT NOT NULL DEFAULT 'visitor',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_path TEXT NOT NULL DEFAULT '/',
    referrer TEXT NOT NULL DEFAULT '',
    device TEXT NOT NULL DEFAULT 'Unknown',
    page_views INTEGER NOT NULL DEFAULT 0,
    latitude_approx REAL,
    longitude_approx REAL,
    location_shared INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS visitor_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visitor_key TEXT NOT NULL,
    user_id INTEGER,
    event_type TEXT NOT NULL,
    path TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_attempts (
    identity_key TEXT PRIMARY KEY,
    window_started TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_listings_public ON listings(status, approval_status, payment_status, category);
CREATE INDEX IF NOT EXISTS idx_listings_owner ON listings(owner_id, posted_at);
CREATE INDEX IF NOT EXISTS idx_interests_listing ON interests(listing_id, created_at);
CREATE INDEX IF NOT EXISTS idx_visitor_events_time ON visitor_events(created_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_db(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
        admin = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
        if not admin:
            username = os.environ.get("ADMIN_USERNAME", "admin").strip() or "admin"
            email = os.environ.get("ADMIN_EMAIL", "").strip() or None
            password = os.environ.get("ADMIN_PASSWORD")
            generated = False
            if not password:
                password = secrets.token_urlsafe(15)
                generated = True
            conn.execute(
                "INSERT INTO users(role,account_type,full_name,email,phone,password_hash,verified,created_at) VALUES('admin','admin',?,?,?,?,1,?)",
                (username, email, "", generate_password_hash(password), now_iso()),
            )
            if generated:
                print("\n=== INITIAL ADMIN LOGIN ===")
                print(f"Admin path: {ADMIN_ROOT}")
                print(f"Username: {username}")
                print(f"Password (copy now; stored as a hash): {password}")
                print("Set ADMIN_USERNAME and ADMIN_PASSWORD in Render environment variables and keep these credentials private.\n")
        conn.execute("PRAGMA journal_mode = WAL")


init_db()


def create_db_snapshot(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = connect_db()
    try:
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
    finally:
        source.close()
    return destination


def maybe_daily_backup() -> None:
    stamp = datetime.now().strftime("%Y-%m-%d")
    existing = list(BACKUP_DIR.glob(f"auto-{stamp}-*.sqlite3"))
    if not existing and DB_PATH.exists() and DB_PATH.stat().st_size > 0:
        target = BACKUP_DIR / f"auto-{stamp}-{datetime.now().strftime('%H%M%S')}.sqlite3"
        try:
            create_db_snapshot(target)
            backups = sorted(BACKUP_DIR.glob("auto-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[14:]:
                old.unlink(missing_ok=True)
        except Exception as exc:
            print(f"WARNING: automatic SQLite backup failed: {exc}")


maybe_daily_backup()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect_db()
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        try:
            if _error is None:
                db.commit()
            else:
                db.rollback()
        finally:
            db.close()


def setting(key: str, default: str = "") -> str:
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    get_db().execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def all_settings() -> dict[str, str]:
    return {row["key"]: row["value"] for row in get_db().execute("SELECT key,value FROM settings")}


def get_current_user():
    if not getattr(g, "_current_user_loaded", False):
        uid = session.get("user_id")
        g.current_user = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
        g._current_user_loaded = True
    return g.current_user


def refresh_current_user_cache():
    g._current_user_loaded = False
    g.current_user = None


def csrf_field() -> Markup:
    token = session.get("csrf_token", "")
    return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')


@app.before_request
def prepare_request():
    if not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_urlsafe(24)
    if not session.get("visitor_key"):
        session["visitor_key"] = secrets.token_urlsafe(20)
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRFToken", "")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            abort(400, description="Your form session expired. Refresh the page and try again.")
    if request.endpoint not in {"static", "manifest", "service_worker", "icon_svg", "robots_txt", "sitemap_xml", "qr_platform"}:
        try:
            maybe_daily_backup()
        except Exception:
            pass


def audit(action: str, target_type: str = "", target_id: str | int = "", details: str = "") -> None:
    user = get_current_user()
    get_db().execute(
        "INSERT INTO audit_log(actor_id,action,target_type,target_id,details,created_at) VALUES(?,?,?,?,?,?)",
        (user["id"] if user else None, action, target_type, str(target_id), details[:2000], now_iso()),
    )


def _auth_attempt_key(scope: str) -> str:
    # Store a short-lived keyed fingerprint, never the raw network address.
    address = request.remote_addr or "unknown"
    value = f"{scope}:{address}".encode("utf-8", "ignore")
    return hmac.new(app.secret_key.encode("utf-8"), value, hashlib.sha256).hexdigest()


def auth_is_limited(scope: str) -> bool:
    key = _auth_attempt_key(scope)
    row = get_db().execute("SELECT window_started,attempts FROM auth_attempts WHERE identity_key=?", (key,)).fetchone()
    if not row:
        return False
    try:
        started = datetime.fromisoformat(row["window_started"])
    except ValueError:
        return False
    if datetime.now(timezone.utc) - started > timedelta(minutes=15):
        get_db().execute("DELETE FROM auth_attempts WHERE identity_key=?", (key,))
        return False
    return row["attempts"] >= 8


def auth_failed(scope: str) -> None:
    key = _auth_attempt_key(scope)
    row = get_db().execute("SELECT window_started,attempts FROM auth_attempts WHERE identity_key=?", (key,)).fetchone()
    expired = False
    if row:
        try:
            expired = datetime.now(timezone.utc) - datetime.fromisoformat(row["window_started"]) > timedelta(minutes=15)
        except ValueError:
            expired = True
    if not row or expired:
        get_db().execute("INSERT INTO auth_attempts(identity_key,window_started,attempts) VALUES(?,?,1) ON CONFLICT(identity_key) DO UPDATE SET window_started=excluded.window_started,attempts=1", (key, now_iso()))
    else:
        get_db().execute("UPDATE auth_attempts SET attempts=attempts+1 WHERE identity_key=?", (key,))


def auth_succeeded(scope: str) -> None:
    get_db().execute("DELETE FROM auth_attempts WHERE identity_key=?", (_auth_attempt_key(scope),))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not get_current_user():
            flash("Please sign in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def partner_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash("Sign in to manage your properties.", "info")
            return redirect(url_for("partner_login", next=request.path))
        if user["role"] not in {"owner", "agent", "host", "business"}:
            flash("This page is for property partners.", "warning")
            return redirect(url_for("index"))
        if user["suspended"]:
            abort(403, description="This partner account is temporarily suspended. Contact support.")
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_current_user()
        if not user or user["role"] != "admin":
            flash("Administrator sign-in is required.", "warning")
            return redirect(ADMIN_ROOT)
        return view(*args, **kwargs)
    return wrapped


def money(value) -> str:
    try:
        return f"KES {float(value):,.0f}"
    except (TypeError, ValueError):
        return "Price on request"


def safe_external_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return ""
    return value


def public_base() -> str:
    configured = safe_external_url(setting("public_base_url", "") or os.environ.get("PUBLIC_BASE_URL", ""))
    return configured.rstrip("/") if configured else request.url_root.rstrip("/")


def fee_for_category(category: str) -> float:
    meta = CATEGORY_META.get(category, CATEGORY_META["residential"])
    try:
        return max(0, float(setting(meta["fee"], DEFAULT_SETTINGS[meta["fee"]])))
    except ValueError:
        return 0


def listing_images(row) -> list[str]:
    try:
        return json.loads(row["images"] or "[]")
    except (TypeError, json.JSONDecodeError):
        return []


def freshness_threshold() -> str:
    try:
        days = max(1, min(365, int(setting("listing_expiry_days", "14"))))
    except ValueError:
        days = 14
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def is_public_listing(row) -> bool:
    if not row:
        return False
    owner = get_db().execute("SELECT verified,suspended FROM users WHERE id=?", (row["owner_id"],)).fetchone()
    confirmed = row["last_confirmed_at"] if "last_confirmed_at" in row.keys() else ""
    fresh = bool(confirmed and confirmed >= freshness_threshold())
    return bool(owner and owner["verified"] and not owner["suspended"] and row["payment_status"] == "paid" and row["approval_status"] == "approved" and row["property_verified"] and row["status"] == "available" and fresh)


def log_event(event_type: str, path: str, details: str = "") -> None:
    try:
        user = get_current_user()
        visitor_key = session.get("visitor_key", "")
        get_db().execute(
            "INSERT INTO visitor_events(visitor_key,user_id,event_type,path,details,created_at) VALUES(?,?,?,?,?,?)",
            (visitor_key, user["id"] if user else None, event_type, path[:500], details[:1500], now_iso()),
        )
    except Exception as exc:
        print(f"Visitor event not recorded: {exc}")


def device_label(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if any(token in ua for token in ("mobile", "android", "iphone", "ipad")):
        return "Mobile / tablet"
    if ua:
        return "Desktop"
    return "Unknown"


@app.after_request
def record_page_view(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
    if request.path.startswith(("/manage-admin", ADMIN_ROOT, "/partner/", "/login", "/join")):
        response.headers["Cache-Control"] = "no-store"
    if request.method == "GET" and response.status_code < 400 and request.endpoint not in {
        "static", "manifest", "service_worker", "icon_svg", "robots_txt", "sitemap_xml", "qr_platform", "listing_qr"
    }:
        try:
            user = get_current_user()
            visitor_key = session.get("visitor_key", "")
            existing = get_db().execute("SELECT visitor_key FROM visitor_sessions WHERE visitor_key=?", (visitor_key,)).fetchone()
            role = "administrator" if user and user["role"] == "admin" else (
                "partner" if user and user["role"] in {"owner", "agent", "host", "business"} else
                "house seeker" if user and user["role"] == "seeker" else "visitor"
            )
            referrer = ""
            if request.referrer:
                try:
                    referrer = urlparse(request.referrer).netloc[:200]
                except Exception:
                    referrer = ""
            if existing:
                get_db().execute(
                    "UPDATE visitor_sessions SET user_id=?,role=?,last_seen=?,last_path=?,referrer=?,device=?,page_views=page_views+1 WHERE visitor_key=?",
                    (user["id"] if user else None, role, now_iso(), request.path[:500], referrer, device_label(request.headers.get("User-Agent", "")), visitor_key),
                )
            else:
                get_db().execute(
                    "INSERT INTO visitor_sessions(visitor_key,user_id,role,first_seen,last_seen,last_path,referrer,device,page_views) VALUES(?,?,?,?,?,?,?,?,1)",
                    (visitor_key, user["id"] if user else None, role, now_iso(), now_iso(), request.path[:500], referrer, device_label(request.headers.get("User-Agent", ""))),
                )
            get_db().execute(
                "INSERT INTO visitor_events(visitor_key,user_id,event_type,path,details,created_at) VALUES(?,?,?,?,?,?)",
                (visitor_key, user["id"] if user else None, "page_view", request.path[:500], role, now_iso()),
            )
        except Exception as exc:
            print(f"Visitor analytics not recorded: {exc}")
    return response


@app.context_processor
def inject_globals():
    user = get_current_user()
    return {
        "site_settings": all_settings(),
        "current_user": user,
        "csrf_field": csrf_field,
        "listing_images": listing_images,
        "category_meta": CATEGORY_META,
        "money": money,
        "admin_root": ADMIN_ROOT,
        "current_year": datetime.now().year,
    }


def safe_next_url(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("/") and not value.startswith("//"):
        return value
    return None


def save_upload(file, target_dir: Path, allowed: set[str]) -> str:
    if not file or not file.filename:
        return ""
    original = secure_filename(file.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in allowed:
        raise ValueError(f"Unsupported file type for {original}. Allowed: {', '.join(sorted(allowed))}.")
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > MAX_FILE_BYTES:
        raise ValueError(f"{original} is too large. Each image/document must be no more than {MAX_FILE_BYTES // (1024*1024)} MB.")
    target_dir.mkdir(parents=True, exist_ok=True)
    if ext == "pdf":
        header = file.stream.read(5)
        file.stream.seek(0)
        if header != b"%PDF-":
            raise ValueError(f"{original} does not look like a valid PDF document.")
        filename = f"{uuid.uuid4().hex}.pdf"
        file.save(target_dir / filename)
        return filename
    try:
        with Image.open(file.stream) as probe:
            probe.verify()
        file.stream.seek(0)
        with Image.open(file.stream) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((1800, 1600), Image.Resampling.LANCZOS)
            filename = f"{uuid.uuid4().hex}.webp"
            image.save(target_dir / filename, format="WEBP", quality=86, method=5)
            image.close()
        file.stream.seek(0)
        return filename
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"{original} is not a valid supported image. Upload a real JPG, PNG or WebP file.") from exc


def public_listings(where: str = "", params: tuple = (), limit: int = 100):
    sql = """
        SELECT l.*,u.full_name AS partner_name,u.business_name,u.role AS partner_role,u.verified AS partner_verified
        FROM listings l JOIN users u ON u.id=l.owner_id
        WHERE l.status='available' AND l.approval_status='approved' AND l.payment_status='paid'
          AND l.property_verified=1 AND u.verified=1 AND u.suspended=0
    """
    if where:
        sql += " AND " + where
    sql += " AND l.last_confirmed_at >= ?"
    sql += " ORDER BY CASE WHEN l.featured_until > ? THEN 0 ELSE 1 END, l.posted_at DESC LIMIT ?"
    return get_db().execute(sql, (*params, freshness_threshold(), now_iso(), limit)).fetchall()


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dlat, dlon = math.radians(float(lat2) - float(lat1)), math.radians(float(lon2) - float(lon1))
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.route("/")
def index():
    rows = public_listings(limit=12)
    counts = {key: get_db().execute("SELECT COUNT(*) FROM listings l JOIN users u ON u.id=l.owner_id WHERE l.category=? AND l.status='available' AND l.approval_status='approved' AND l.payment_status='paid' AND l.property_verified=1 AND l.last_confirmed_at>=? AND u.verified=1 AND u.suspended=0", (key, freshness_threshold())).fetchone()[0] for key in CATEGORY_META}
    partners = get_db().execute("SELECT u.id,u.full_name,u.business_name,u.role,COUNT(l.id) AS listing_count FROM users u LEFT JOIN listings l ON l.owner_id=u.id AND l.status='available' AND l.approval_status='approved' AND l.payment_status='paid' AND l.property_verified=1 WHERE u.role IN ('owner','agent','host','business') AND u.verified=1 AND u.suspended=0 GROUP BY u.id ORDER BY listing_count DESC,u.full_name LIMIT 6").fetchall()
    visitor_count = get_db().execute("SELECT COUNT(DISTINCT visitor_key) FROM visitor_events WHERE event_type='page_view'").fetchone()[0]
    return render_template("index.html", listings=rows, counts=counts, partners=partners, visitor_count=visitor_count)


@app.route("/homes")
def homes():
    q = request.args.get("q", "").strip()[:120]
    category = request.args.get("category", "").strip()
    property_type = request.args.get("type", "").strip()
    location = request.args.get("location", "").strip()[:120]
    max_price = request.args.get("max_price", "").strip()
    min_beds = request.args.get("bedrooms", "").strip()
    params = []
    clauses = []
    if category in CATEGORY_META:
        clauses.append("l.category=?"); params.append(category)
    if property_type:
        clauses.append("l.property_type=?"); params.append(property_type)
    if q:
        clauses.append("(l.title LIKE ? OR l.description LIKE ? OR l.location_name LIKE ? OR l.landmarks LIKE ? OR l.property_type LIKE ?)")
        params.extend([f"%{q}%"] * 5)
    if location:
        clauses.append("(l.location_name LIKE ? OR l.landmarks LIKE ?)"); params.extend([f"%{location}%", f"%{location}%"])
    if max_price:
        try:
            clauses.append("l.price_amount<=?"); params.append(float(max_price))
        except ValueError:
            max_price = ""
    if min_beds:
        try:
            clauses.append("COALESCE(l.bedrooms,0)>=?"); params.append(int(min_beds))
        except ValueError:
            min_beds = ""
    where = " AND ".join(clauses)
    results = public_listings(where, tuple(params), 200)
    user_lat, user_lon = request.args.get("lat", ""), request.args.get("lon", "")
    if user_lat and user_lon:
        try:
            latf, lonf = float(user_lat), float(user_lon)
            results = sorted(results, key=lambda r: haversine_km(latf, lonf, r["latitude"], r["longitude"]) if r["latitude"] is not None and r["longitude"] is not None else 1e9)
        except (ValueError, TypeError):
            pass
    log_event("property_search", request.path, json.dumps({"q": q, "category": category, "location": location, "max_price": max_price, "bedrooms": min_beds, "count": len(results)}))
    return render_template("homes.html", listings=results, q=q, category=category, property_type=property_type, location=location, max_price=max_price, bedrooms=min_beds, types=CATEGORY_META.get(category, {}).get("types", []), sorted_by_distance=bool(user_lat and user_lon))


@app.route("/listing/<int:listing_id>")
def listing_detail(listing_id: int):
    row = get_db().execute("SELECT l.*,u.full_name AS partner_name,u.business_name,u.role AS partner_role,u.phone AS partner_phone,u.verified AS partner_verified FROM listings l JOIN users u ON l.owner_id=u.id WHERE l.id=?", (listing_id,)).fetchone()
    if not row or not is_public_listing(row):
        abort(404)
    get_db().execute("UPDATE listings SET views=views+1 WHERE id=?", (listing_id,))
    log_event("listing_view", request.path, json.dumps({"listing_id": listing_id, "category": row["category"]}))
    try:
        posted = datetime.fromisoformat(row["posted_at"])
        posted_display = posted.strftime("%d %b %Y")
    except (ValueError, TypeError):
        posted_display = row["posted_at"][:10]
    return render_template("listing_detail.html", listing=row, images=listing_images(row), category=CATEGORY_META.get(row["category"], CATEGORY_META["residential"]), posted_display=posted_display)


@app.post("/listing/<int:listing_id>/interest")
def express_interest(listing_id: int):
    row = get_db().execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    if not row or not is_public_listing(row):
        abort(404)
    name = request.form.get("full_name", "").strip()[:120]
    phone = request.form.get("phone", "").strip()[:40]
    email = request.form.get("email", "").strip()[:160]
    message = request.form.get("message", "").strip()[:2000]
    if not name or not phone:
        flash("Please add your name and phone number so the property partner can reply.", "error")
        return redirect(url_for("listing_detail", listing_id=listing_id) + "#interest")
    user = get_current_user()
    cur = get_db().execute("INSERT INTO interests(listing_id,seeker_id,full_name,phone,email,message,created_at) VALUES(?,?,?,?,?,?,?)", (listing_id, user["id"] if user and user["role"] == "seeker" else None, name, phone, email, message, now_iso()))
    log_event("interest_submitted", request.path, json.dumps({"listing_id": listing_id, "interest_id": cur.lastrowid}))
    audit("interest_submitted", "listing", listing_id, f"Enquiry submitted by {name}")
    flash("Your interest has been sent. The property partner can now contact you to confirm availability and viewing details.", "success")
    return redirect(url_for("listing_detail", listing_id=listing_id) + "#interest")


@app.post("/listing/<int:listing_id>/report-taken")
def report_taken(listing_id: int):
    row = get_db().execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    if not row or not is_public_listing(row):
        abort(404)
    reason = request.form.get("reason", "").strip()[:800] or "Reported as no longer available"
    user = get_current_user()
    name = (user["full_name"] if user else request.form.get("reporter_name", "Visitor").strip()[:120])
    get_db().execute("INSERT INTO reports(listing_id,reporter_id,reporter_name,reason,created_at) VALUES(?,?,?,?,?)", (listing_id, user["id"] if user else None, name, reason, now_iso()))
    get_db().execute("UPDATE listings SET status='reported_taken',updated_at=? WHERE id=?", (now_iso(), listing_id))
    log_event("listing_reported_taken", request.path, json.dumps({"listing_id": listing_id}))
    audit("listing_reported_taken", "listing", listing_id, reason)
    flash("Thank you. The listing has been hidden while the report is reviewed by an administrator.", "success")
    return redirect(url_for("homes"))


@app.route("/privacy")
def privacy_policy():
    return render_template("privacy.html")


@app.route("/terms")
def terms_of_use():
    return render_template("terms.html")


@app.route("/partners")
def partners_directory():
    rows = get_db().execute("SELECT u.id,u.full_name,u.business_name,u.role,u.created_at,COUNT(l.id) AS listing_count FROM users u LEFT JOIN listings l ON l.owner_id=u.id AND l.status='available' AND l.approval_status='approved' AND l.payment_status='paid' AND l.property_verified=1 WHERE u.role IN ('owner','agent','host','business') AND u.verified=1 AND u.suspended=0 GROUP BY u.id ORDER BY listing_count DESC,u.full_name").fetchall()
    return render_template("partners.html", partners=rows)


@app.route("/partner/register", methods=["GET", "POST"])
def partner_register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()[:120]
        business_name = request.form.get("business_name", "").strip()[:160]
        role = request.form.get("role", "owner").strip()
        email = request.form.get("email", "").strip().lower()[:160] or None
        phone = request.form.get("phone", "").strip()[:40]
        password = request.form.get("password", "")
        identity_type = request.form.get("identity_type", "national_id").strip()
        front_file = request.files.get("identity_front")
        back_file = request.files.get("identity_back")
        if role not in {"owner", "agent", "host", "business"}:
            role = "owner"
        if not full_name or not phone or not password or len(password) < 10:
            flash("Add your name and phone, and use a password of at least 10 characters.", "error")
            return render_template("partner_register.html", form=request.form)
        if not front_file or not front_file.filename or not back_file or not back_file.filename:
            flash("Upload both sides of the identity document to request partner verification.", "error")
            return render_template("partner_register.html", form=request.form)
        try:
            front = save_upload(front_file, PRIVATE_DOC_DIR, ALLOWED_DOC_EXTENSIONS)
            back = save_upload(back_file, PRIVATE_DOC_DIR, ALLOWED_DOC_EXTENSIONS)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("partner_register.html", form=request.form)
        try:
            cur = get_db().execute("INSERT INTO users(role,account_type,full_name,business_name,email,phone,password_hash,identity_type,identity_front,identity_back,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (role, role, full_name, business_name, email, phone, generate_password_hash(password), identity_type, front, back, now_iso()))
        except sqlite3.IntegrityError:
            flash("That email address is already registered. Please sign in instead or use another email.", "error")
            return render_template("partner_register.html", form=request.form)
        session.clear()
        session["user_id"] = cur.lastrowid
        session["csrf_token"] = secrets.token_urlsafe(24)
        session["visitor_key"] = secrets.token_urlsafe(20)
        refresh_current_user_cache()
        audit("partner_registered", "user", cur.lastrowid, f"Partner role={role}")
        flash("Partner application received. Your identity check is pending. You can submit listings and payment references, but nothing publishes until the required checks pass.", "success")
        return redirect(url_for("partner_dashboard"))
    return render_template("partner_register.html", form={})


@app.route("/partner/login", methods=["GET", "POST"])
def partner_login():
    if request.method == "POST":
        if auth_is_limited("partner"):
            flash("Too many unsuccessful sign-in attempts. Try again in 15 minutes.", "error")
            return render_template("partner_login.html"), 429
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE (lower(email)=? OR phone=?) AND role IN ('owner','agent','host','business')", (identity, identity)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            auth_failed("partner")
            flash("Those sign-in details did not match a partner account.", "error")
        elif user["suspended"]:
            flash("This partner account is temporarily suspended. Please contact support.", "error")
        else:
            auth_succeeded("partner")
            session.clear(); session["user_id"] = user["id"]; session["csrf_token"] = secrets.token_urlsafe(24); session["visitor_key"] = secrets.token_urlsafe(20)
            refresh_current_user_cache()
            get_db().execute("UPDATE users SET last_login=? WHERE id=?", (now_iso(), user["id"]))
            audit("partner_login", "user", user["id"])
            return redirect(safe_next_url(request.args.get("next")) or url_for("partner_dashboard"))
    return render_template("partner_login.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if auth_is_limited("seeker"):
            flash("Too many unsuccessful sign-in attempts. Try again in 15 minutes.", "error")
            return render_template("login.html"), 429
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE (lower(email)=? OR phone=?) AND role='seeker'", (identity, identity)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            auth_failed("seeker")
            flash("Those sign-in details did not match a house-seeker account.", "error")
        elif user["suspended"]:
            flash("This account is temporarily suspended.", "error")
        else:
            auth_succeeded("seeker")
            session.clear(); session["user_id"] = user["id"]; session["csrf_token"] = secrets.token_urlsafe(24); session["visitor_key"] = secrets.token_urlsafe(20)
            refresh_current_user_cache()
            get_db().execute("UPDATE users SET last_login=? WHERE id=?", (now_iso(), user["id"]))
            audit("seeker_login", "user", user["id"])
            return redirect(safe_next_url(request.args.get("next")) or url_for("index"))
    return render_template("login.html")


@app.route("/join", methods=["GET", "POST"])
def join():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()[:120]
        phone = request.form.get("phone", "").strip()[:40]
        email = request.form.get("email", "").strip().lower()[:160] or None
        password = request.form.get("password", "")
        if not name or not phone or len(password) < 10:
            flash("Add your name and phone number, and use a password of at least 10 characters.", "error")
        else:
            try:
                cur = get_db().execute("INSERT INTO users(role,account_type,full_name,email,phone,password_hash,created_at) VALUES('seeker','seeker',?,?,?,?,?)", (name, email, phone, generate_password_hash(password), now_iso()))
                session.clear(); session["user_id"] = cur.lastrowid; session["csrf_token"] = secrets.token_urlsafe(24); session["visitor_key"] = secrets.token_urlsafe(20)
                refresh_current_user_cache()
                audit("seeker_registered", "user", cur.lastrowid)
                flash("Your house-seeker account is ready.", "success")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                flash("That email address is already registered. Please sign in.", "error")
    return render_template("join.html")


@app.post("/logout")
@login_required
def logout():
    user = get_current_user()
    audit("logout", "user", user["id"] if user else "")
    session.clear()
    return redirect(url_for("index"))


@app.route("/partner/dashboard")
@partner_required
def partner_dashboard():
    user = get_current_user()
    listings = get_db().execute("SELECT * FROM listings WHERE owner_id=? ORDER BY posted_at DESC", (user["id"],)).fetchall()
    interests = get_db().execute("SELECT i.*,l.title AS listing_title,l.owner_id FROM interests i JOIN listings l ON l.id=i.listing_id WHERE l.owner_id=? ORDER BY i.created_at DESC LIMIT 30", (user["id"],)).fetchall()
    stats = {
        "listings": len(listings),
        "published": sum(1 for x in listings if x["status"] == "available" and x["approval_status"] == "approved" and x["payment_status"] == "paid" and x["property_verified"]),
        "enquiries": get_db().execute("SELECT COUNT(*) FROM interests i JOIN listings l ON i.listing_id=l.id WHERE l.owner_id=?", (user["id"],)).fetchone()[0],
    }
    return render_template("partner_dashboard.html", listings=listings, interests=interests, stats=stats)


@app.route("/partner/management")
@partner_required
def partner_management():
    target = safe_external_url(setting("management_url", ""))
    if target:
        return redirect(target, code=302)
    return render_template("management_not_connected.html")


@app.route("/partner/listings/new", methods=["GET", "POST"])
@partner_required
def partner_new_listing():
    user = get_current_user()
    if request.method == "POST":
        category = request.form.get("category", "residential")
        if category not in CATEGORY_META:
            category = "residential"
        property_type = request.form.get("property_type", "").strip()[:120]
        title = request.form.get("title", "").strip()[:180]
        description = request.form.get("description", "").strip()[:5000]
        location_name = request.form.get("location_name", "").strip()[:180]
        landmarks = request.form.get("landmarks", "").strip()[:1200]
        price_period = request.form.get("price_period", "per month").strip()
        property_condition = request.form.get("property_condition", "").strip()[:120]
        if price_period not in PRICE_PERIODS:
            price_period = "per month"
        try:
            price_amount = float(request.form.get("price_amount", "0") or 0)
            deposit_amount = float(request.form.get("deposit_amount", "") or 0)
            bedrooms = int(request.form.get("bedrooms", "") or 0) or None
            bathrooms = int(request.form.get("bathrooms", "") or 0) or None
        except ValueError:
            flash("Check that rent, deposit and bedroom fields contain valid numbers.", "error")
            return render_template("listing_form.html", form=request.form, categories=CATEGORY_META, price_periods=PRICE_PERIODS)
        floor_area = request.form.get("floor_area", "").strip()[:80]
        amenities = request.form.get("amenities", "").strip()[:1200]
        try:
            latitude = float(request.form.get("latitude", "").strip()) if request.form.get("latitude", "").strip() else None
            longitude = float(request.form.get("longitude", "").strip()) if request.form.get("longitude", "").strip() else None
            if latitude is not None and not -90 <= latitude <= 90: raise ValueError()
            if longitude is not None and not -180 <= longitude <= 180: raise ValueError()
        except ValueError:
            flash("Map coordinates are not valid. Use the map pin or leave coordinates blank for now.", "error")
            return render_template("listing_form.html", form=request.form, categories=CATEGORY_META, price_periods=PRICE_PERIODS)
        if not title or not property_type or not location_name or price_amount < 0:
            flash("Please complete property name, type, location and price.", "error")
            return render_template("listing_form.html", form=request.form, categories=CATEGORY_META, price_periods=PRICE_PERIODS)
        if latitude is None or longitude is None:
            flash("Add the property's map coordinates to help house seekers reach the real location. You can save this listing, but it cannot be approved until its location is checked.", "info")
        image_names = []
        try:
            for file in request.files.getlist("images")[:8]:
                if file and file.filename:
                    image_names.append(save_upload(file, LISTING_UPLOAD_DIR, ALLOWED_IMAGE_EXTENSIONS))
        except ValueError as exc:
            for name in image_names: (LISTING_UPLOAD_DIR / name).unlink(missing_ok=True)
            flash(str(exc), "error")
            return render_template("listing_form.html", form=request.form, categories=CATEGORY_META, price_periods=PRICE_PERIODS)
        if not image_names:
            flash("Upload at least one genuine property photo so the review team can assess the listing.", "error")
            return render_template("listing_form.html", form=request.form, categories=CATEGORY_META, price_periods=PRICE_PERIODS)
        fee = fee_for_category(category)
        payment_reference = request.form.get("payment_reference", "").strip()[:120]
        payment_status = "submitted" if payment_reference else "pending"
        cur = get_db().execute("""INSERT INTO listings(owner_id,category,property_type,title,description,price_amount,price_period,deposit_amount,bedrooms,bathrooms,floor_area,amenities,location_name,landmarks,latitude,longitude,property_condition,images,status,approval_status,payment_status,payment_reference,fee_amount,posted_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending','pending',?,?,?,?,?)""",
            (user["id"], category, property_type, title, description, price_amount, price_period, deposit_amount, bedrooms, bathrooms, floor_area, amenities, location_name, landmarks, latitude, longitude, property_condition, json.dumps(image_names), payment_status, payment_reference, fee, now_iso(), now_iso()))
        listing_id = cur.lastrowid
        log_event("property_submitted", request.path, json.dumps({"listing_id": listing_id, "category": category}))
        audit("property_submitted", "listing", listing_id, f"Fee {fee}; payment reference supplied={bool(payment_reference)}")
        flash("Listing saved privately. It will not appear in public searches until the payment is confirmed, your partner account is verified, and an administrator approves the property.", "success")
        return redirect(url_for("partner_dashboard"))
    return render_template("listing_form.html", form={}, categories=CATEGORY_META, price_periods=PRICE_PERIODS)


@app.route("/partner/listings/<int:listing_id>/edit", methods=["GET", "POST"])
@partner_required
def partner_edit_listing(listing_id):
    user = get_current_user()
    row = get_db().execute("SELECT * FROM listings WHERE id=? AND owner_id=?", (listing_id, user["id"])).fetchone()
    if not row:
        abort(404)
    if request.method == "POST":
        category = request.form.get("category", row["category"])
        if category not in CATEGORY_META:
            category = row["category"]
        property_type = request.form.get("property_type", "").strip()[:120]
        title = request.form.get("title", "").strip()[:180]
        description = request.form.get("description", "").strip()[:5000]
        location_name = request.form.get("location_name", "").strip()[:180]
        landmarks = request.form.get("landmarks", "").strip()[:1200]
        price_period = request.form.get("price_period", "per month").strip()
        condition = request.form.get("property_condition", "").strip()[:120]
        if price_period not in PRICE_PERIODS: price_period = "per month"
        try:
            price_amount = float(request.form.get("price_amount", "0") or 0)
            deposit_amount = float(request.form.get("deposit_amount", "") or 0)
            bedrooms = int(request.form.get("bedrooms", "") or 0) or None
            bathrooms = int(request.form.get("bathrooms", "") or 0) or None
            latitude = float(request.form.get("latitude", "").strip()) if request.form.get("latitude", "").strip() else None
            longitude = float(request.form.get("longitude", "").strip()) if request.form.get("longitude", "").strip() else None
            if latitude is not None and not -90 <= latitude <= 90: raise ValueError()
            if longitude is not None and not -180 <= longitude <= 180: raise ValueError()
        except ValueError:
            flash("Check the price, room and coordinate fields.", "error")
            return redirect(url_for("partner_edit_listing", listing_id=listing_id))
        if not title or not property_type or not location_name or price_amount < 0:
            flash("Property name, type, location and price are required.", "error")
            return redirect(url_for("partner_edit_listing", listing_id=listing_id))
        names = listing_images(row)
        try:
            additions = []
            for file in request.files.getlist("images")[:8]:
                if file and file.filename:
                    additions.append(save_upload(file, LISTING_UPLOAD_DIR, ALLOWED_IMAGE_EXTENSIONS))
            if additions:
                names = (names + additions)[-8:]
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("partner_edit_listing", listing_id=listing_id))
        if not names:
            flash("At least one genuine property photo is required.", "error")
            return redirect(url_for("partner_edit_listing", listing_id=listing_id))
        fee = fee_for_category(category)
        payment_status = row["payment_status"]
        payment_reference = row["payment_reference"]
        if category != row["category"]:
            payment_status = "pending"
            payment_reference = ""
        elif row["payment_status"] == "paid":
            fee = float(row["fee_amount"])
        # Any substantive edit puts the property back into the review queue.
        get_db().execute("""UPDATE listings SET category=?,property_type=?,title=?,description=?,price_amount=?,price_period=?,deposit_amount=?,bedrooms=?,bathrooms=?,floor_area=?,amenities=?,location_name=?,landmarks=?,latitude=?,longitude=?,property_condition=?,images=?,status='pending',approval_status='pending',payment_status=?,payment_reference=?,fee_amount=?,property_verified=0,last_confirmed_at='',updated_at=? WHERE id=? AND owner_id=?""",
            (category, property_type, title, description, price_amount, price_period, deposit_amount, bedrooms, bathrooms, request.form.get("floor_area", "").strip()[:80], request.form.get("amenities", "").strip()[:1200], location_name, landmarks, latitude, longitude, condition, json.dumps(names), payment_status, payment_reference, fee, now_iso(), listing_id, user["id"]))
        audit("partner_edited_property", "listing", listing_id, "Listing returned to verification queue after edit")
        flash("Listing updated and returned to review. It stays private until the property is checked again. If its category changed, the new fee must be paid.", "success")
        return redirect(url_for("partner_dashboard"))
    form = dict(row)
    return render_template("listing_form.html", form=form, categories=CATEGORY_META, price_periods=PRICE_PERIODS, edit_mode=True, existing_images=listing_images(row), existing_listing=row)


@app.route("/partner/listings/<int:listing_id>/availability", methods=["POST"])
@partner_required
def partner_confirm_availability(listing_id):
    user = get_current_user()
    row = get_db().execute("SELECT * FROM listings WHERE id=? AND owner_id=?", (listing_id, user["id"])).fetchone()
    if not row:
        abort(404)
    action = request.form.get("availability", "available")
    if action == "taken":
        get_db().execute("UPDATE listings SET status='occupied',updated_at=? WHERE id=?", (now_iso(), listing_id))
        audit("partner_marked_taken", "listing", listing_id)
        flash("The property is now marked as taken and is hidden from available searches.", "success")
    elif action == "available":
        # Partners can re-confirm but cannot unilaterally reverse an admin-reviewed taken/report status.
        if row["status"] in {"occupied", "reported_taken"}:
            flash("An administrator must review a taken/report status before the property can be listed again.", "warning")
        elif row["approval_status"] == "approved" and row["payment_status"] == "paid" and row["property_verified"]:
            get_db().execute("UPDATE listings SET status='available',last_confirmed_at=?,updated_at=? WHERE id=?", (now_iso(), now_iso(), listing_id))
            audit("availability_confirmed", "listing", listing_id)
            flash("Availability confirmation recorded.", "success")
        else:
            flash("This property is not yet approved for publication.", "warning")
    return redirect(url_for("partner_dashboard"))


@app.route("/manage-admin", methods=["GET"])
def admin_base_redirect():
    return redirect(ADMIN_ROOT)


def admin_entry():
    user = get_current_user()
    if user and user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        if auth_is_limited("admin"):
            flash("Too many unsuccessful sign-in attempts. Try again in 15 minutes.", "error")
            return render_template("admin_login.html", admin_path=ADMIN_ROOT), 429
        identity = request.form.get("identity", "").strip()
        password = request.form.get("password", "")
        admin = get_db().execute("SELECT * FROM users WHERE role='admin' AND full_name=? LIMIT 1", (identity,)).fetchone()
        if not admin and identity:
            admin = get_db().execute("SELECT * FROM users WHERE role='admin' AND lower(COALESCE(email,''))=lower(?) LIMIT 1", (identity,)).fetchone()
        if not admin or not check_password_hash(admin["password_hash"], password):
            auth_failed("admin")
            flash("Administrator sign-in failed.", "error")
            return render_template("admin_login.html", admin_path=ADMIN_ROOT)
        auth_succeeded("admin")
        session.clear(); session["user_id"] = admin["id"]; session["csrf_token"] = secrets.token_urlsafe(24); session["visitor_key"] = secrets.token_urlsafe(20)
        refresh_current_user_cache()
        get_db().execute("UPDATE users SET last_login=? WHERE id=?", (now_iso(), admin["id"]))
        audit("admin_login", "user", admin["id"])
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_login.html", admin_path=ADMIN_ROOT)


app.add_url_rule(ADMIN_ROOT, endpoint="admin_entry", view_func=admin_entry, methods=["GET", "POST"])


@app.route("/manage-admin/logout", methods=["POST"])
@admin_required
def admin_logout():
    audit("admin_logout", "user", get_current_user()["id"])
    session.clear()
    return redirect(ADMIN_ROOT)


@app.route("/manage-admin/dashboard")
@admin_required
def admin_dashboard():
    conn = get_db()
    stats = {
        "listings": conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
        "published": conn.execute("SELECT COUNT(*) FROM listings WHERE status='available' AND approval_status='approved' AND payment_status='paid' AND property_verified=1").fetchone()[0],
        "pending_payment": conn.execute("SELECT COUNT(*) FROM listings WHERE payment_status IN ('pending','submitted')").fetchone()[0],
        "pending_review": conn.execute("SELECT COUNT(*) FROM listings WHERE payment_status='paid' AND approval_status='pending'").fetchone()[0],
        "partners": conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('owner','agent','host','business')").fetchone()[0],
        "partners_pending": conn.execute("SELECT COUNT(*) FROM users WHERE role IN ('owner','agent','host','business') AND verified=0 AND suspended=0").fetchone()[0],
        "interests": conn.execute("SELECT COUNT(*) FROM interests").fetchone()[0],
        "reports": conn.execute("SELECT COUNT(*) FROM reports WHERE status='open'").fetchone()[0],
        "visitors_today": conn.execute("SELECT COUNT(DISTINCT visitor_key) FROM visitor_events WHERE event_type='page_view' AND created_at>=?", (datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).isoformat(),)).fetchone()[0],
    }
    listings = conn.execute("SELECT l.*,u.full_name AS partner_name,u.business_name FROM listings l JOIN users u ON u.id=l.owner_id ORDER BY l.posted_at DESC LIMIT 8").fetchall()
    latest_events = conn.execute("SELECT * FROM visitor_events ORDER BY id DESC LIMIT 10").fetchall()
    return render_template("admin_dashboard.html", stats=stats, listings=listings, events=latest_events)


@app.route("/manage-admin/listings")
@admin_required
def admin_listings():
    status = request.args.get("status", "").strip()
    category = request.args.get("category", "").strip()
    clauses, params = [], []
    if status:
        clauses.append("l.status=?"); params.append(status)
    if category in CATEGORY_META:
        clauses.append("l.category=?"); params.append(category)
    sql = "SELECT l.*,u.full_name AS partner_name,u.business_name,u.phone AS partner_phone,u.verified AS partner_verified FROM listings l JOIN users u ON l.owner_id=u.id"
    if clauses: sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY l.posted_at DESC LIMIT 300"
    listings = get_db().execute(sql, params).fetchall()
    return render_template("admin_listings.html", listings=listings, status=status, category=category)


@app.post("/manage-admin/listings/<int:listing_id>/action")
@admin_required
def admin_listing_action(listing_id):
    row = get_db().execute("SELECT l.*,u.verified AS owner_verified FROM listings l JOIN users u ON u.id=l.owner_id WHERE l.id=?", (listing_id,)).fetchone()
    if not row: abort(404)
    action = request.form.get("action", "")
    if action == "mark_paid":
        reference = (request.form.get("payment_reference", "").strip() or row["payment_reference"] or "")[:120]
        if not reference:
            flash("Add and reconcile the actual payment reference before marking this listing paid.", "error")
        else:
            get_db().execute("UPDATE listings SET payment_status='paid',payment_reference=?,updated_at=? WHERE id=?", (reference, now_iso(), listing_id))
            audit("payment_confirmed_manually", "listing", listing_id, f"ref={reference}")
            flash("Payment marked as confirmed. Listing approval is still a separate step.", "success")
    elif action == "approve":
        if request.form.get("checks_confirmed") != "yes":
            flash("Confirm that you checked the property's existence and the partner's authority to advertise it.", "error")
        elif row["payment_status"] != "paid":
            flash("Cannot approve a listing until payment is confirmed.", "error")
        elif not row["owner_verified"]:
            flash("Verify the owner/agent account first.", "error")
        elif row["latitude"] is None or row["longitude"] is None:
            flash("Add and verify the property's actual map coordinates before approval.", "error")
        elif not listing_images(row):
            flash("A property photo is required before approval.", "error")
        else:
            get_db().execute("UPDATE listings SET approval_status='approved',property_verified=1,status='available',last_confirmed_at=?,updated_at=? WHERE id=?", (now_iso(), now_iso(), listing_id))
            audit("listing_verified_and_approved", "listing", listing_id)
            flash("Property approved and published. It now passes the payment, partner and property verification gates.", "success")
    elif action == "reject":
        get_db().execute("UPDATE listings SET approval_status='rejected',status='rejected',updated_at=? WHERE id=?", (now_iso(), listing_id))
        audit("listing_rejected", "listing", listing_id, request.form.get("reason", "")[:500])
        flash("Listing rejected and kept out of public search.", "success")
    elif action == "mark_taken":
        get_db().execute("UPDATE listings SET status='occupied',updated_at=? WHERE id=?", (now_iso(), listing_id))
        audit("admin_marked_taken", "listing", listing_id)
        flash("Listing marked as taken.", "success")
    elif action == "reinstate":
        if row["payment_status"] == "paid" and row["approval_status"] == "approved" and row["property_verified"] and row["owner_verified"]:
            get_db().execute("UPDATE listings SET status='available',last_confirmed_at=?,updated_at=? WHERE id=?", (now_iso(), now_iso(), listing_id))
            audit("admin_reinstated_listing", "listing", listing_id)
            flash("Listing reinstated by administrator.", "success")
        else:
            flash("This listing does not meet all publication checks and cannot be reinstated.", "error")
    elif action == "remove":
        get_db().execute("UPDATE listings SET status='removed',approval_status='rejected',updated_at=? WHERE id=?", (now_iso(), listing_id))
        audit("listing_removed", "listing", listing_id, request.form.get("reason", "")[:500])
        flash("Listing removed from public results. Its history has been retained.", "success")
    else:
        flash("Unknown listing action.", "error")
    return redirect(url_for("admin_listings"))


@app.route("/manage-admin/partners")
@admin_required
def admin_partners():
    rows = get_db().execute("SELECT u.*, (SELECT COUNT(*) FROM listings l WHERE l.owner_id=u.id) AS listing_count FROM users u WHERE u.role IN ('owner','agent','host','business') ORDER BY u.created_at DESC").fetchall()
    return render_template("admin_partners.html", partners=rows)


@app.post("/manage-admin/partners/<int:user_id>/action")
@admin_required
def admin_partner_action(user_id):
    user = get_db().execute("SELECT * FROM users WHERE id=? AND role IN ('owner','agent','host','business')", (user_id,)).fetchone()
    if not user: abort(404)
    action = request.form.get("action", "")
    if action == "verify":
        if not user["identity_front"] or not user["identity_back"]:
            flash("Cannot verify this partner: both identity document sides are missing.", "error")
        else:
            get_db().execute("UPDATE users SET verified=1,suspended=0 WHERE id=?", (user_id,))
            audit("partner_identity_verified", "user", user_id)
            flash("Partner verified. Property listings still require their own checks and confirmed payment.", "success")
    elif action == "unverify":
        get_db().execute("UPDATE users SET verified=0 WHERE id=?", (user_id,))
        audit("partner_verification_revoked", "user", user_id)
        flash("Partner verification removed. Their listings no longer appear in public search.", "success")
    elif action == "suspend":
        get_db().execute("UPDATE users SET suspended=1 WHERE id=?", (user_id,))
        audit("partner_suspended", "user", user_id)
        flash("Partner suspended.", "success")
    elif action == "restore":
        get_db().execute("UPDATE users SET suspended=0 WHERE id=?", (user_id,))
        audit("partner_restored", "user", user_id)
        flash("Partner account restored.", "success")
    return redirect(url_for("admin_partners"))


@app.route("/manage-admin/documents/<path:filename>")
@admin_required
def admin_private_document(filename):
    allowed_names = set()
    for row in get_db().execute("SELECT identity_front,identity_back FROM users"):
        if row["identity_front"]: allowed_names.add(row["identity_front"])
        if row["identity_back"]: allowed_names.add(row["identity_back"])
    if filename not in allowed_names or Path(filename).name != filename:
        abort(404)
    response = send_from_directory(PRIVATE_DOC_DIR, filename, as_attachment=True, max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.route("/manage-admin/interests")
@admin_required
def admin_interests():
    rows = get_db().execute("SELECT i.*,l.title AS listing_title,l.category,u.full_name AS partner_name FROM interests i JOIN listings l ON l.id=i.listing_id JOIN users u ON u.id=l.owner_id ORDER BY i.created_at DESC LIMIT 500").fetchall()
    return render_template("admin_interests.html", interests=rows)


@app.post("/manage-admin/interests/<int:interest_id>/action")
@admin_required
def admin_interest_action(interest_id):
    row = get_db().execute("SELECT * FROM interests WHERE id=?", (interest_id,)).fetchone()
    if not row: abort(404)
    status = request.form.get("status", "contacted")
    if status not in {"new", "contacted", "viewing", "closed", "spam"}: status = "contacted"
    get_db().execute("UPDATE interests SET status=? WHERE id=?", (status, interest_id))
    audit("interest_status_changed", "interest", interest_id, status)
    flash("Enquiry status updated.", "success")
    return redirect(url_for("admin_interests"))


@app.route("/manage-admin/reports")
@admin_required
def admin_reports():
    rows = get_db().execute("SELECT r.*,l.title AS listing_title,l.status AS listing_status,l.owner_id,l.location_name FROM reports r JOIN listings l ON l.id=r.listing_id ORDER BY CASE r.status WHEN 'open' THEN 0 ELSE 1 END,r.created_at DESC LIMIT 500").fetchall()
    return render_template("admin_reports.html", reports=rows)


@app.post("/manage-admin/reports/<int:report_id>/action")
@admin_required
def admin_report_action(report_id):
    row = get_db().execute("SELECT r.*,l.status AS listing_status,l.payment_status,l.approval_status,l.property_verified,l.latitude,l.longitude,l.owner_id FROM reports r JOIN listings l ON l.id=r.listing_id WHERE r.id=?", (report_id,)).fetchone()
    if not row: abort(404)
    action = request.form.get("action", "")
    if action == "confirm_taken":
        get_db().execute("UPDATE listings SET status='occupied',updated_at=? WHERE id=(SELECT listing_id FROM reports WHERE id=?)", (now_iso(), report_id))
        get_db().execute("UPDATE reports SET status='confirmed_taken',resolved_at=? WHERE id=?", (now_iso(), report_id))
        audit("report_confirmed_taken", "report", report_id)
        flash("Report confirmed. Property remains hidden as taken.", "success")
    elif action == "reinstate":
        owner = get_db().execute("SELECT verified,suspended FROM users WHERE id=?", (row["owner_id"],)).fetchone()
        if row["payment_status"] == "paid" and row["approval_status"] == "approved" and row["property_verified"] and owner and owner["verified"] and not owner["suspended"] and row["latitude"] is not None and row["longitude"] is not None:
            get_db().execute("UPDATE listings SET status='available',last_confirmed_at=?,updated_at=? WHERE id=(SELECT listing_id FROM reports WHERE id=?)", (now_iso(), now_iso(), report_id))
            get_db().execute("UPDATE reports SET status='dismissed',resolved_at=? WHERE id=?", (now_iso(), report_id))
            audit("report_dismissed_and_listing_reinstated", "report", report_id)
            flash("Report dismissed and listing reinstated by administrator.", "success")
        else:
            flash("Cannot reinstate: the listing no longer passes all checks. Review payment, partner and property verification first.", "error")
    elif action == "dismiss":
        get_db().execute("UPDATE reports SET status='dismissed',resolved_at=? WHERE id=?", (now_iso(), report_id))
        audit("report_dismissed", "report", report_id)
        flash("Report dismissed. The listing status was not changed automatically; check it separately.", "success")
    return redirect(url_for("admin_reports"))


@app.route("/manage-admin/analytics")
@admin_required
def admin_analytics():
    conn = get_db()
    sessions = conn.execute("SELECT v.*,u.full_name,u.business_name FROM visitor_sessions v LEFT JOIN users u ON v.user_id=u.id ORDER BY v.last_seen DESC LIMIT 250").fetchall()
    top_pages = conn.execute("SELECT path,COUNT(*) AS hits,COUNT(DISTINCT visitor_key) AS visitors FROM visitor_events WHERE event_type='page_view' GROUP BY path ORDER BY hits DESC LIMIT 15").fetchall()
    search_rows = conn.execute("SELECT details,created_at FROM visitor_events WHERE event_type='property_search' ORDER BY id DESC LIMIT 30").fetchall()
    totals = {
        "sessions": conn.execute("SELECT COUNT(*) FROM visitor_sessions").fetchone()[0],
        "shared": conn.execute("SELECT COUNT(*) FROM visitor_sessions WHERE location_shared=1").fetchone()[0],
        "today": conn.execute("SELECT COUNT(DISTINCT visitor_key) FROM visitor_events WHERE event_type='page_view' AND created_at>=?", (datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).isoformat(),)).fetchone()[0],
    }
    return render_template("admin_analytics.html", sessions=sessions, top_pages=top_pages, search_rows=search_rows, totals=totals)


@app.post("/api/location")
def save_opt_in_location():
    payload = request.get_json(silent=True) or {}
    if payload.get("consent") is not True:
        return jsonify({"ok": False, "error": "Explicit location consent is required."}), 400
    try:
        lat, lon = float(payload.get("latitude")), float(payload.get("longitude"))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError()
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Coordinates were not valid."}), 400
    # Keep approximate neighborhood-level coordinates, not a precise movement history.
    lat = round(lat, 3); lon = round(lon, 3)
    key = session.get("visitor_key", "")
    user = get_current_user()
    conn = get_db()
    exists = conn.execute("SELECT visitor_key FROM visitor_sessions WHERE visitor_key=?", (key,)).fetchone()
    if exists:
        conn.execute("UPDATE visitor_sessions SET latitude_approx=?,longitude_approx=?,location_shared=1,user_id=?,last_seen=? WHERE visitor_key=?", (lat, lon, user["id"] if user else None, now_iso(), key))
    else:
        role = "partner" if user and user["role"] in {"owner", "agent", "host", "business"} else "house seeker" if user and user["role"] == "seeker" else "visitor"
        conn.execute("INSERT INTO visitor_sessions(visitor_key,user_id,role,first_seen,last_seen,last_path,device,page_views,latitude_approx,longitude_approx,location_shared) VALUES(?,?,?,?,?,?,?,?,?,?,1)", (key, user["id"] if user else None, role, now_iso(), now_iso(), request.referrer or "/", device_label(request.headers.get("User-Agent", "")), 0, lat, lon))
    conn.execute("INSERT INTO visitor_events(visitor_key,user_id,event_type,path,details,created_at) VALUES(?,?,?,?,?,?)", (key, user["id"] if user else None, "location_shared_with_consent", request.path, "Approximate coordinates rounded to 3 decimal places", now_iso()))
    return jsonify({"ok": True, "latitude": lat, "longitude": lon})


@app.route("/manage-admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        allowed_keys = set(DEFAULT_SETTINGS.keys())
        for key in allowed_keys:
            if key.endswith("_enabled"):
                value = "1" if request.form.get(key) else "0"
            elif key in request.form:
                value = request.form.get(key, "").strip()
            else:
                continue
            if key in {"brand_primary", "brand_accent"} and not (len(value) == 7 and value.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in value[1:])):
                flash(f"{key.replace('_',' ').title()} must be a valid hex color.", "error")
                return redirect(url_for("admin_settings"))
            if key == "management_url" and value and not safe_external_url(value):
                flash("Management URL must begin with https:// or http:// and include a valid host.", "error")
                return redirect(url_for("admin_settings"))
            if key == "public_base_url" and value and not safe_external_url(value):
                flash("Public base URL must begin with https:// or http:// and include a valid host.", "error")
                return redirect(url_for("admin_settings"))
            if key.endswith("_url") and key.startswith("social_") and value and not safe_external_url(value):
                flash("Social profile links must be valid http:// or https:// URLs.", "error")
                return redirect(url_for("admin_settings"))
            if key.startswith("fee_"):
                try:
                    number = float(value)
                    if number < 0 or number > 100000000: raise ValueError()
                    value = str(round(number, 2))
                except ValueError:
                    flash(f"{key.replace('_',' ').title()} must be a non-negative number.", "error")
                    return redirect(url_for("admin_settings"))
            if key == "listing_expiry_days":
                try:
                    days = int(value)
                    if not 1 <= days <= 365: raise ValueError()
                except ValueError:
                    flash("Listing expiry must be between 1 and 365 days.", "error")
                    return redirect(url_for("admin_settings"))
            set_setting(key, value)
        new_password = request.form.get("new_admin_password", "")
        if new_password:
            if len(new_password) < 12:
                flash("New administrator password must be at least 12 characters.", "error")
                return redirect(url_for("admin_settings"))
            admin = get_current_user()
            get_db().execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_password), admin["id"]))
            audit("admin_password_changed", "user", admin["id"])
        audit("settings_updated", "settings", "all", "Site name, brand, fees and configuration updated")
        flash("Settings saved. New fees apply to newly submitted listings; existing invoice amounts stay recorded on their listings.", "success")
        return redirect(url_for("admin_settings"))
    return render_template("admin_settings.html", settings=all_settings())


@app.route("/manage-admin/backups")
@admin_required
def admin_backups():
    files = sorted(BACKUP_DIR.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    backups = [{"name": p.name, "size": p.stat().st_size, "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%d %b %Y %H:%M"), "url": url_for("admin_download_backup", filename=p.name)} for p in files[:50]]
    return render_template("admin_backups.html", backups=backups, db_size=DB_PATH.stat().st_size if DB_PATH.exists() else 0)


@app.post("/manage-admin/backups/create")
@admin_required
def admin_create_backup():
    filename = f"manual-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    path = create_db_snapshot(BACKUP_DIR / filename)
    audit("manual_database_backup_created", "backup", filename, f"{path.stat().st_size} bytes")
    flash(f"Full SQLite backup created: {filename}", "success")
    return redirect(url_for("admin_backups"))


@app.route("/manage-admin/backups/download-current")
@admin_required
def admin_download_current_backup():
    filename = f"patamahali-full-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
    path = create_db_snapshot(BACKUP_DIR / filename)
    audit("database_backup_downloaded", "backup", filename)
    return send_file(path, as_attachment=True, download_name=filename, mimetype="application/vnd.sqlite3", max_age=0)


@app.route("/manage-admin/backups/<path:filename>")
@admin_required
def admin_download_backup(filename):
    if Path(filename).name != filename or not filename.endswith(".sqlite3"):
        abort(404)
    path = BACKUP_DIR / filename
    if not path.is_file(): abort(404)
    audit("backup_downloaded", "backup", filename)
    return send_file(path, as_attachment=True, download_name=filename, mimetype="application/vnd.sqlite3", max_age=0)


@app.post("/manage-admin/backups/restore")
@admin_required
def admin_restore_backup():
    file = request.files.get("backup_file")
    if not file or not file.filename:
        flash("Choose a SQLite backup file first.", "error")
        return redirect(url_for("admin_backups"))
    ext = Path(secure_filename(file.filename)).suffix.lower()
    if ext not in {".sqlite3", ".sqlite", ".db"}:
        flash("Choose a .sqlite3, .sqlite or .db file.", "error")
        return redirect(url_for("admin_backups"))
    temp_upload = BACKUP_DIR / f"restore-upload-{uuid.uuid4().hex}{ext}"
    try:
        file.save(temp_upload)
        if temp_upload.stat().st_size < 1024:
            raise ValueError("The file is too small to be a complete database.")
        test_conn = sqlite3.connect(f"file:{temp_upload}?mode=ro", uri=True)
        try:
            check = test_conn.execute("PRAGMA quick_check").fetchone()
            tables = {r[0] for r in test_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"settings", "users", "listings", "interests", "visitor_sessions", "visitor_events", "reports", "audit_log", "auth_attempts"}
            if not check or check[0] != "ok" or not required.issubset(tables):
                raise ValueError("This file is not a valid backup for this site.")
        finally:
            test_conn.close()
        create_db_snapshot(BACKUP_DIR / f"before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3")
        # Close this request's connection, then restore through SQLite's backup API.
        # This preserves SQLite journaling semantics better than replacing a live DB file.
        close_db()
        source_conn = sqlite3.connect(str(temp_upload), timeout=30)
        target_conn = connect_db(DB_PATH)
        try:
            source_conn.backup(target_conn)
            target_conn.commit()
            integrity = target_conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("Restored database failed the integrity check.")
        finally:
            source_conn.close()
            target_conn.close()
        refresh_current_user_cache()
        audit_conn = connect_db()
        try:
            admin_id = session.get("user_id")
            valid_admin = audit_conn.execute("SELECT id FROM users WHERE id=? AND role='admin'", (admin_id,)).fetchone() if admin_id else None
            actor_id = valid_admin["id"] if valid_admin else None
            audit_conn.execute("INSERT INTO audit_log(actor_id,action,target_type,target_id,details,created_at) VALUES(?,?,?,?,?,?)", (actor_id, "database_restored", "backup", secure_filename(file.filename), "Database replaced after SQLite integrity and schema validation", now_iso()))
            audit_conn.commit()
            if not valid_admin:
                session.clear()
                refresh_current_user_cache()
        finally:
            audit_conn.close()
        flash("Database restored from the selected backup. A safety backup of the previous database was created first.", "success")
    except Exception as exc:
        flash(f"Restore failed: {exc}", "error")
    finally:
        temp_upload.unlink(missing_ok=True)
    return redirect(url_for("admin_backups"))


@app.route("/media/<path:filename>")
def listing_media(filename):
    if Path(filename).name != filename or Path(filename).suffix.lower().lstrip(".") not in ALLOWED_IMAGE_EXTENSIONS:
        abort(404)
    row = get_db().execute("SELECT id,images,status,approval_status,payment_status,property_verified FROM listings WHERE images LIKE ? LIMIT 1", (f"%{filename}%",)).fetchone()
    if not row:
        abort(404)
    owner = get_db().execute("SELECT verified,suspended FROM users WHERE id=(SELECT owner_id FROM listings WHERE id=?)", (row["id"],)).fetchone()
    # Photos for unapproved listings are visible only to the owning partner or admin.
    if not (row["status"] == "available" and row["approval_status"] == "approved" and row["payment_status"] == "paid" and row["property_verified"] and owner and owner["verified"] and not owner["suspended"]):
        user = get_current_user()
        listing_owner = get_db().execute("SELECT owner_id FROM listings WHERE id=?", (row["id"],)).fetchone()
        if not user or (user["role"] != "admin" and user["id"] != listing_owner["owner_id"]):
            abort(404)
    response = send_from_directory(LISTING_UPLOAD_DIR, filename, max_age=86400)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/qr/platform.png")
def qr_platform():
    url = public_base() + "/"
    return qr_response(url, "platform")


@app.route("/qr/listing/<int:listing_id>.png")
def listing_qr(listing_id):
    row = get_db().execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    if not row or not is_public_listing(row): abort(404)
    return qr_response(public_base() + url_for("listing_detail", listing_id=listing_id), f"listing-{listing_id}")


def qr_response(url: str, filename: str):
    from io import BytesIO
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=3)
    qr.add_data(url); qr.make(fit=True)
    image = qr.make_image(fill_color="#163D31", back_color="#FFFFFF")
    out = BytesIO(); image.save(out, format="PNG"); out.seek(0)
    return send_file(out, mimetype="image/png", download_name=f"{filename}.png", max_age=3600)


@app.route("/manifest.webmanifest")
def manifest():
    from flask import Response
    body = {
        "name": setting("site_name", "PataMahali"),
        "short_name": setting("site_name", "PataMahali")[:12],
        "description": setting("site_description", "Verified property marketplace"),
        "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#f8f7f1", "theme_color": setting("brand_primary", "#176B4D"),
        "icons": [{"src": url_for("icon_svg"), "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
    }
    return app.response_class(json.dumps(body), mimetype="application/manifest+json")


@app.route("/service-worker.js")
def service_worker():
    response = send_from_directory(BASE_DIR / "static" / "js", "service-worker.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/icon.svg")
def icon_svg():
    return send_from_directory(BASE_DIR / "static" / "img", "icon.svg", mimetype="image/svg+xml")


@app.route("/robots.txt")
def robots_txt():
    base = public_base()
    return app.response_class(f"User-agent: *\nDisallow: {ADMIN_ROOT}\nDisallow: /manage-admin/\nDisallow: /partner/\nDisallow: /login\nDisallow: /join\nDisallow: /media/\nSitemap: {base}/sitemap.xml\n", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    from xml.sax.saxutils import escape
    base = public_base()
    locs = [base + "/", base + "/homes", base + "/partners"]
    rows = public_listings(limit=10000)
    for row in rows:
        locs.append(base + url_for("listing_detail", listing_id=row["id"]))
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(f"<url><loc>{escape(loc)}</loc></url>" for loc in locs) + "</urlset>"
    return app.response_class(xml, mimetype="application/xml")


@app.errorhandler(413)
def too_large(_error):
    return render_template("error.html", code=413, message="That upload is too large. Please reduce the file size and try again."), 413


@app.errorhandler(403)
def forbidden(error):
    return render_template("error.html", code=403, message=getattr(error, "description", "You do not have access to this page.")), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We could not find that page or the listing is not publicly available."), 404


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=getattr(error, "description", "Please refresh and try again.")), 400


@app.errorhandler(500)
def server_error(error):
    # Log detail for owner/developer, keep internal exception data out of visitor pages.
    print(f"Internal server error: {error}")
    return render_template("error.html", code=500, message="Something went wrong. Please try again."), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
