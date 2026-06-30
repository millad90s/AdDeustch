"""FastAPI backend for the German DevOps flashcard app.

Words and sentences are shared by everyone. Spaced-repetition scheduling runs
in the browser; this server just serves the shared deck and (for logged-in
users) persists per-user progress. Google login is optional.
"""
import os
import re
import secrets
import threading
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

try:
    from minio import Minio
    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False

import ai
import db
import paypal
from seed import SEED_WORDS
from seed_grammar import SEED_GRAMMAR

load_dotenv()

# Logged-in users whose email is in this list may add/delete words.
ADMIN_EMAILS = {
    e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
}
# The AI provider is resolved per request (so dashboard settings changes apply
# without a restart). Construction is cheap — it just reads config.
def get_ai():
    return ai.get_provider()


# Token cost per paid service. Today only AI sentence generation is metered;
# add more services here as the app grows.
TOKEN_COST_GENERATE = int(os.getenv("TOKEN_COST_GENERATE", "1"))  # per word generated

STATIC_DIR = Path(__file__).parent / "static"
# Uploaded reading audio lives next to the database (so it sits on the same
# persistent volume in Docker) and is served from /media/...
MEDIA_DIR = Path(os.getenv("MEDIA_DIR") or (db.DB_PATH.parent / "media"))

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
AUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

# Enrichment service for sentence generation
ENRICHMENT_ENDPOINT = os.getenv("ENRICHMENT_ENDPOINT", "http://localhost:7000")
ENRICHMENT_ENABLED = os.getenv("ENRICHMENT_ENABLED", "true").lower() in ("1", "true", "yes")

# MinIO configuration for image storage
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "milad")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "12345678")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "flashcard-ads")
MINIO_USE_SSL = os.getenv("MINIO_USE_SSL", "false").lower() in ("1", "true", "yes")
MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "http://127.0.0.1:9000")
MINIO_CLIENT = None
if MINIO_AVAILABLE:
    try:
        MINIO_CLIENT = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=MINIO_USE_SSL)
    except Exception as e:
        print(f"Warning: Could not initialize MinIO client: {e}")

app = FastAPI(title="German DevOps Flashcards")
_behind_proxy = os.getenv("BEHIND_PROXY", "").lower() in ("1", "true", "yes")
# ProxyHeadersMiddleware must be added FIRST so X-Forwarded-Proto is rewritten
# before SessionMiddleware sees the request scheme (needed for https_only cookies).
if _behind_proxy:
    from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=_behind_proxy,
)

# --- Google OAuth (only wired up if credentials are present) ---
oauth = None
if AUTH_ENABLED:
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------
class SentenceIn(BaseModel):
    sentence_de: str = Field(min_length=1)
    sentence_en: str = Field(min_length=1)


class WordIn(BaseModel):
    word: str = Field(min_length=1)
    category: str = "general"
    level: str = "B1"  # CEFR level this word is taught at (A1–C2)
    sentences: list[SentenceIn] = []
    lemma: str | None = None  # base form of word
    pos: str | None = None  # part of speech (noun, verb, adj, etc.)
    article: str | None = None  # der, die, das
    audio_url: str | None = None  # pronunciation audio link
    word_url: str | None = None  # link to word info
    image_url: str | None = None  # link to word image
    unit_id: int | None = None  # lesson unit ID
    tags: list[str] = []  # tags for categorization and ad matching


class ProgressIn(BaseModel):
    reps: int = 0
    interval: int = 0
    ease: float = 2.5
    lapses: int = 0
    due: str  # ISO date, e.g. "2026-06-23"


class GrammarIn(BaseModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)  # Markdown
    category: str = "general"
    position: int = 0


class ProfileIn(BaseModel):
    career: str = "general"
    level: str = "B1"
    location: str | None = None
    daily_goal: int = Field(default=10, ge=1, le=100)


class LearningIn(BaseModel):
    learned: list[int] = []
    wrong: dict[int, int] = {}


class GenerateIn(BaseModel):
    career: str = "general"
    level: str = "B1"
    n: int = Field(default=3, ge=1, le=6)


class NoteIn(BaseModel):
    note: str = ""


class GrantTokensIn(BaseModel):
    email: str
    amount: int = Field(ge=1, le=100000)


class ReadingIn(BaseModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)  # Markdown story
    level: str = "B1"
    position: int = 0
    audio_url: str | None = None     # direct audio URL (or a Drive share link)
    id: int | None = None  # set to update an existing reading


_DRIVE_RE = re.compile(r"drive\.google\.com/file/d/([A-Za-z0-9_-]+)")


def normalize_audio_url(url):
    """Turn a Google Drive *share* link into a more-direct download URL. Other
    URLs (S3/R2/nginx/our own /media/...) are returned unchanged."""
    url = (url or "").strip()
    if not url:
        return ""
    m = _DRIVE_RE.search(url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


class PackageIn(BaseModel):
    tokens: int = Field(ge=1, le=1_000_000)
    price: float = Field(ge=0.5, le=100000)   # in major units (e.g. euros)
    currency: str = "EUR"
    active: bool = True
    position: int = 0
    id: int | None = None  # set to update an existing package


class SettingsIn(BaseModel):
    # All optional; only provided fields are saved. Blank API-key fields are
    # ignored (keep the existing key) so the masked value isn't written back.
    ai_provider: str | None = None
    anthropic_model: str | None = None
    anthropic_api_key: str | None = None
    gemini_model: str | None = None
    gemini_api_key: str | None = None


class CreateOrderIn(BaseModel):
    package_id: int


class CaptureOrderIn(BaseModel):
    package_id: int
    order_id: str


class SignupIn(BaseModel):
    email: str
    password: str = Field(min_length=8)
    name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class CompanySignupIn(BaseModel):
    email: str
    password: str = Field(min_length=8)
    name: str
    contact_name: str | None = None
    contact_phone: str | None = None


class CompanyLoginIn(BaseModel):
    email: str
    password: str


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------
# startup & helpers
# --------------------------------------------------------------------------
@app.on_event("startup")
def startup():
    db.init_db()
    if not db.list_words():
        for entry in SEED_WORDS:
            db.add_word(entry["word"], entry.get("category", "general"),
                        entry["sentences"], entry.get("level", "B1"))
    if not db.list_grammar():
        for title, category, position, body in SEED_GRAMMAR:
            db.add_grammar(title, body, category, position)


def current_user(request: Request):
    uid = request.session.get("user_id")
    if uid:
        return db.get_user(uid)

    # Check for Bearer token in Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return db.get_user_by_token(token)

    return None


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "login required")
    return user


def is_admin(user):
    return bool(user) and (user.get("email") or "").lower() in ADMIN_EMAILS


def require_admin(request: Request):
    user = require_user(request)
    if not is_admin(user):
        raise HTTPException(403, "admin access required")
    return user


def _public_user(user):
    return {
        "name": user.get("name"), "email": user.get("email"),
        "picture": user.get("picture"), "is_admin": is_admin(user),
        "tokens": user.get("tokens", 0),
    }


def current_company(request: Request):
    cid = request.session.get("company_id")
    return db.get_company(cid) if cid else None


def require_company(request: Request):
    company = current_company(request)
    if not company:
        raise HTTPException(401, "company login required")
    return company


def _req_meta(request: Request):
    """Pull useful info from the request headers (client IP, browser, language…)."""
    h = request.headers
    fwd = h.get("x-forwarded-for")
    ip = (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None))
    return {
        "ip": ip,
        "user_agent": h.get("user-agent"),
        "language": h.get("accept-language"),
        "referer": h.get("referer"),
    }


def _record_access(user_id, event, request: Request):
    m = _req_meta(request)
    db.log_access(user_id, event, m["ip"], m["user_agent"], m["language"],
                  m["referer"], request.url.path)


# --------------------------------------------------------------------------
# auth — local email/password accounts
# --------------------------------------------------------------------------
@app.post("/auth/signup")
def auth_signup(body: SignupIn, request: Request):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Please enter a valid email address.")
    try:
        user = db.create_local_user(email, body.password, (body.name or "").strip() or None)
    except ValueError:
        raise HTTPException(409, "An account with this email already exists.")
    request.session["user_id"] = user["id"]
    _record_access(user["id"], "signup", request)
    return {"ok": True, "user": _public_user(user)}


@app.post("/auth/login")
def auth_login_local(body: LoginIn, request: Request):
    user = db.authenticate(body.email.strip().lower(), body.password)
    if not user:
        raise HTTPException(401, "Invalid email or password.")
    request.session["user_id"] = user["id"]
    _record_access(user["id"], "login", request)
    return {"ok": True, "user": _public_user(user)}


@app.post("/auth/logout")
async def auth_logout(request: Request):
    request.session.pop("user_id", None)
    return {"ok": True}


# --------------------------------------------------------------------------
# company auth — email/password for companies
# --------------------------------------------------------------------------
@app.post("/auth/company/signup")
def company_signup(body: CompanySignupIn, request: Request):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Please enter a valid email address.")
    try:
        company = db.create_company(email, body.password, body.name, body.contact_name, body.contact_phone)
    except ValueError:
        raise HTTPException(409, "An account with this email already exists.")
    request.session["company_id"] = company["id"]
    return {"ok": True, "company": {"id": company["id"], "name": company["name"], "email": company["email"], "approved": company["approved"]}}


@app.post("/auth/company/login")
def company_login(body: CompanyLoginIn, request: Request):
    company = db.authenticate_company(body.email.strip().lower(), body.password)
    if not company:
        raise HTTPException(401, "Invalid email or password.")
    request.session["company_id"] = company["id"]
    return {"ok": True, "company": {"id": company["id"], "name": company["name"], "email": company["email"], "approved": company["approved"]}}


@app.post("/auth/company/logout")
async def company_logout(request: Request):
    request.session.pop("company_id", None)
    return {"ok": True}


@app.get("/api/me/company")
def api_me_company(request: Request):
    company = current_company(request)
    return {
        "company": None if not company else {"id": company["id"], "name": company["name"], "email": company["email"], "approved": company["approved"]},
    }


# --------------------------------------------------------------------------
# auth — Google OAuth (optional)
# --------------------------------------------------------------------------
@app.get("/auth/google")
async def auth_google(request: Request):
    if not AUTH_ENABLED:
        raise HTTPException(503, "Google login is not configured on this server.")
    return await oauth.google.authorize_redirect(request, OAUTH_REDIRECT_URI)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    if not AUTH_ENABLED:
        raise HTTPException(503, "Google login is not configured on this server.")
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        # User denied permission or other OAuth error occurred
        return RedirectResponse("/?auth_error=Google+login+was+cancelled")
    info = token.get("userinfo") or {}
    if not info.get("sub"):
        raise HTTPException(400, "Could not read Google profile.")
    user, _ = db.upsert_user(
        info["sub"], info.get("email"), info.get("name"), info.get("picture")
    )
    request.session["user_id"] = user["id"]
    _record_access(user["id"], "google", request)
    return RedirectResponse("/")


@app.get("/api/me")
def api_me(request: Request):
    user = current_user(request)
    return {
        "google_enabled": AUTH_ENABLED,
        "ai_enabled": get_ai().available(),
        "paypal_enabled": paypal.enabled(),
        "paypal_client_id": paypal.client_id() if paypal.enabled() else "",
        "user": None if not user else _public_user(user),
    }


# --------------------------------------------------------------------------
# shared deck (words + sentences)
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.svg")
def favicon():
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/dashboard")
def dashboard_page():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/clogin")
def company_login_page():
    return FileResponse(STATIC_DIR / "clogin.html")


@app.get("/cdashboard")
def company_dashboard_page():
    return FileResponse(STATIC_DIR / "cdashboard.html")


@app.get("/api/admin/dashboard")
def api_admin_dashboard(request: Request):
    require_admin(request)
    return db.admin_dashboard()


# ---- AI provider settings (managed from the dashboard) ----
def _resolved(db_key, env_key, default=""):
    return db.get_setting(db_key) or os.getenv(env_key) or default


@app.get("/api/admin/settings")
def api_admin_get_settings(request: Request):
    """Return the current AI config. API keys are never returned — only whether
    each is set and where it comes from (the dashboard or an env var)."""
    require_admin(request)
    prov = get_ai()

    def key_info(db_key, env_key):
        return {"set": bool(_resolved(db_key, env_key)),
                "source": "dashboard" if db.get_setting(db_key) else ("env" if os.getenv(env_key) else "none")}

    return {
        "providers": list(ai.PROVIDERS),
        "ai_provider": _resolved("ai_provider", "AI_PROVIDER", "claude"),
        "anthropic_model": _resolved("anthropic_model", "ANTHROPIC_MODEL", "claude-opus-4-8"),
        "gemini_model": _resolved("gemini_model", "GEMINI_MODEL", "gemini-2.5-flash"),
        "anthropic_key": key_info("anthropic_api_key", "ANTHROPIC_API_KEY"),
        "gemini_key": key_info("gemini_api_key", "GEMINI_API_KEY"),
        "active_provider": prov.name,
        "active_available": prov.available(),
    }


@app.post("/api/admin/settings")
def api_admin_save_settings(body: SettingsIn, request: Request):
    require_admin(request)
    if body.ai_provider:
        p = body.ai_provider.strip().lower()
        if p not in ai.PROVIDERS:
            raise HTTPException(400, "unknown provider")
        db.set_setting("ai_provider", p)
    if body.anthropic_model is not None:
        db.set_setting("anthropic_model", body.anthropic_model.strip())
    if body.gemini_model is not None:
        db.set_setting("gemini_model", body.gemini_model.strip())
    # Only write API keys when a non-blank value is supplied (blank = keep current).
    if body.anthropic_api_key and body.anthropic_api_key.strip():
        db.set_setting("anthropic_api_key", body.anthropic_api_key.strip())
    if body.gemini_api_key and body.gemini_api_key.strip():
        db.set_setting("gemini_api_key", body.gemini_api_key.strip())
    prov = get_ai()
    return {"ok": True, "active_provider": prov.name, "active_available": prov.available()}


@app.get("/api/admin/companies")
def api_admin_companies(request: Request):
    """List pending companies (for admin approval)."""
    require_admin(request)
    pending = db.list_companies(approved=False)
    approved = db.list_companies(approved=True)
    return {"pending": pending, "approved": approved}


@app.put("/api/admin/companies/{company_id}")
def api_admin_approve_company(company_id: int, body: dict, request: Request):
    """Approve or reject a company."""
    require_admin(request)
    approved = body.get("approved", False)
    db.approve_company(company_id, approved)
    return {"ok": True}


@app.get("/api/admin/advertisements")
def api_admin_advertisements(request: Request):
    """List pending advertisements (for admin approval)."""
    require_admin(request)
    pending = db.list_pending_advertisements(approved=False)
    approved = db.list_pending_advertisements(approved=True)
    return {"pending": pending, "approved": approved}


@app.put("/api/admin/advertisements/{ad_id}")
def api_admin_approve_advertisement(ad_id: int, body: dict, request: Request):
    """Approve/reject an advertisement, or toggle active status."""
    require_admin(request)
    approved = body.get("approved")
    active = body.get("active")

    ad = db.get_advertisement(ad_id)
    if not ad:
        raise HTTPException(404, "advertisement not found")

    if approved is not None:
        db.approve_advertisement(ad_id, approved)
    if active is not None:
        db.update_advertisement(ad_id, active=active)

    return {"ok": True}


@app.get("/api/admin/advertisements/{ad_id}/matching-words")
def api_get_matching_words(ad_id: int, request: Request):
    """Get all words whose tags match this ad's tags."""
    require_admin(request)
    words = db.get_words_for_ad(ad_id)
    return {"words": words, "count": len(words)}


# --------------------------------------------------------------------------
# company advertisements
# --------------------------------------------------------------------------
@app.get("/api/tags")
def api_get_tags():
    """Get all available tags from word_tags table."""
    tags = db.get_all_tags()
    return {"tags": tags}


# --------------------------------------------------------------------------
# API tokens (admin only)
# --------------------------------------------------------------------------
@app.get("/api/admin/tokens")
def api_list_tokens(request: Request):
    """List API tokens for the admin user."""
    user = require_admin(request)
    tokens = db.list_api_tokens(user["id"])
    return {"tokens": tokens}


@app.post("/api/admin/tokens")
def api_create_token(body: dict, request: Request):
    """Create a new API token for the admin user."""
    user = require_admin(request)
    name = (body.get("name") or "").strip() or None
    token = db.create_api_token(user["id"], name)
    from datetime import datetime
    return {"token": token, "name": name, "created_at": datetime.utcnow().isoformat()}


@app.delete("/api/admin/tokens/{token_id}")
def api_revoke_token(token_id: int, request: Request):
    """Revoke an API token."""
    user = require_admin(request)
    db.revoke_api_token(user["id"], token_id)
    return {"ok": True}


@app.get("/api/company/ads")
def api_get_company_ads(request: Request):
    """Get all ads for the logged-in company."""
    company = require_company(request)
    ads = db.list_company_ads(company["id"])
    return {"ads": ads}


@app.get("/api/company/ads/{ad_id}")
def api_get_company_ad(ad_id: int, request: Request):
    """Get a specific ad (for editing)."""
    company = require_company(request)
    ad = db.get_advertisement(ad_id)
    if not ad or ad["company_id"] != company["id"]:
        raise HTTPException(404, "advertisement not found")
    return {"ad": ad}


@app.post("/api/company/ads")
def api_create_ad(body: dict, request: Request):
    """Create a new advertisement."""
    company = require_company(request)
    title = (body.get("title") or "").strip()
    description = (body.get("description") or "").strip()
    tags = body.get("tags") or []
    image_url = body.get("image_url")
    image_type = body.get("image_type")

    print(f"\n=== CREATE AD ===")
    print(f"Title: {title}")
    print(f"Description: {description[:50]}...")
    print(f"Tags: {tags}")
    print(f"Image URL: {image_url}")
    print(f"Image Type: {image_type}")
    print(f"Request body: {body}")
    print(f"=================\n")

    if not title or len(title) > 200:
        raise HTTPException(400, "title required (1-200 chars)")
    if not description or len(description) > 2000:
        raise HTTPException(400, "description required (1-2000 chars)")
    if not tags or len(tags) > 20:
        raise HTTPException(400, "tags required (1-20)")

    ad = db.create_advertisement(company["id"], title, description, tags, image_url, image_type)
    print(f"✓ Ad created: {ad}")
    return {"ad": ad}


@app.put("/api/company/ads/{ad_id}")
def api_update_ad(ad_id: int, body: dict, request: Request):
    """Update an advertisement."""
    company = require_company(request)
    ad = db.get_advertisement(ad_id)
    if not ad or ad["company_id"] != company["id"]:
        raise HTTPException(404, "advertisement not found")

    title = (body.get("title") or "").strip() if "title" in body else None
    description = (body.get("description") or "").strip() if "description" in body else None
    tags = body.get("tags") if "tags" in body else None
    image_url = body.get("image_url") if "image_url" in body else None

    if title is not None and (not title or len(title) > 200):
        raise HTTPException(400, "title must be 1-200 chars")
    if description is not None and (not description or len(description) > 2000):
        raise HTTPException(400, "description must be 1-2000 chars")
    if tags is not None and (not tags or len(tags) > 20):
        raise HTTPException(400, "tags must be 1-20")

    db.update_advertisement(ad_id, title, description, tags, image_url)
    return {"ok": True}


@app.delete("/api/company/ads/{ad_id}")
def api_delete_ad(ad_id: int, request: Request):
    """Delete an advertisement."""
    company = require_company(request)
    ad = db.get_advertisement(ad_id)
    if not ad or ad["company_id"] != company["id"]:
        raise HTTPException(404, "advertisement not found")
    db.delete_advertisement(ad_id)
    return {"ok": True}


@app.post("/api/company/ads/{ad_id_or_new}/image")
async def api_upload_ad_image(ad_id_or_new: str, request: Request, file: UploadFile = File(...)):
    """Upload image for an advertisement."""
    print(f"\n=== IMAGE UPLOAD ===")
    print(f"Ad ID: {ad_id_or_new}")
    print(f"File: {file.filename}")
    print(f"Content Type: {file.content_type}")

    company = require_company(request)

    if ad_id_or_new != "new":
        ad = db.get_advertisement(int(ad_id_or_new))
        if not ad or ad["company_id"] != company["id"]:
            raise HTTPException(404, "advertisement not found")

    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "file must be an image")

    # Read and validate file size (5 MB limit)
    contents = await file.read()
    print(f"File size: {len(contents)} bytes")
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(400, "image must be under 5 MB")

    # Save file (MinIO if available, else local filesystem)
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"ads/{company['id']}_{secrets.token_hex(8)}.{ext}"
    image_url = None

    print(f"MINIO_CLIENT: {MINIO_CLIENT}")
    print(f"MINIO_AVAILABLE: {MINIO_AVAILABLE}")
    print(f"Filename: {filename}")

    if MINIO_CLIENT:
        try:
            print(f"🚀 Uploading to MinIO: bucket={MINIO_BUCKET}, key={filename}")
            MINIO_CLIENT.put_object(
                MINIO_BUCKET,
                filename,
                BytesIO(contents),
                length=len(contents),
                content_type=file.content_type,
            )
            image_url = f"{MINIO_PUBLIC_URL}/{MINIO_BUCKET}/{filename}"
            print(f"✓ Image uploaded to MinIO: {image_url}")
        except Exception as e:
            print(f"❌ MinIO upload failed: {e}")
            import traceback
            traceback.print_exc()
            print(f"⚠ Falling back to local filesystem")
            # Fallback to local filesystem
            try:
                file_path = MEDIA_DIR / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "wb") as f:
                    f.write(contents)
                image_url = f"/media/{filename}"
                print(f"✓ Image uploaded to local (fallback): {image_url}")
            except Exception as e2:
                print(f"❌ Local upload also failed: {e2}")
                traceback.print_exc()
    else:
        # No MinIO - use local filesystem
        print(f"📁 No MinIO client, using local filesystem")
        try:
            file_path = MEDIA_DIR / filename
            print(f"File path: {file_path}")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(contents)
            image_url = f"/media/{filename}"
            print(f"✓ Image uploaded to local: {image_url}")
        except Exception as e:
            print(f"❌ Local upload failed: {e}")
            import traceback
            traceback.print_exc()

    print(f"📤 Final image_url: {image_url}")
    print(f"===================\n")
    return {"image_url": image_url}


@app.get("/api/words")
def api_words(request: Request, career: str | None = None):
    # career → each word carries career-relevant + generic sentences and a
    # has_career_sentences flag; no career → every sentence (admin/browse view).
    # Passing the user adds a `paid` flag so the client skips re-requesting words
    # it has already paid for (no needless API calls / cost on refresh).
    user = current_user(request)
    return db.list_words(career, user["id"] if user else None)


# Prevents duplicate Ollama/AI calls for the same (word, career) when multiple
# requests arrive concurrently (e.g. user refreshes mid-generation).
_gen_locks: dict[tuple, threading.Lock] = {}
_gen_locks_mu = threading.Lock()

def _get_gen_lock(word_id: int, career: str) -> threading.Lock:
    key = (word_id, career)
    with _gen_locks_mu:
        if key not in _gen_locks:
            _gen_locks[key] = threading.Lock()
        return _gen_locks[key]


def _call_enrichment_service(word: str, career: str, level: str) -> tuple[list[dict], dict] | None:
    """Call external enrichment service to get word data including sentences.
    Returns tuple of (sentences_list, metadata_dict) or None if failed.

    sentences_list: list of {"de": "...", "en": "...", "tags": [...]}
    metadata_dict contains: audio_url, word_url, meanings, tags
    """
    if not ENRICHMENT_ENABLED:
        return None

    try:
        import requests

        payload = {
            "word": word,
            "career": career,
            "level": level
        }

        print(f"📡 Calling enrichment service: {ENRICHMENT_ENDPOINT}/enrich")
        print(f"📤 Payload: {payload}")

        response = requests.post(
            f"{ENRICHMENT_ENDPOINT}/enrich",
            json=payload,
            timeout=120  # Increased from 30s for AI sentence generation
        )

        print(f"📥 Response status: {response.status_code}")

        if response.status_code != 200:
            print(f"❌ Enrichment service error: {response.status_code}")
            print(f"Response body: {response.text}")
            return None

        data = response.json()
        print(f"✅ Parsed response: {data}")

        # Extract sentences/examples with tags
        examples = data.get("examples", [])
        print(f"📌 Found {len(examples)} examples in response")

        result_sentences = []

        # Parse examples: each should have language=de, example, translation, tags
        for i, ex in enumerate(examples):
            de_text = ex.get("example")
            en_text = ex.get("translation")
            sent_tags = ex.get("tags", data.get("tags", []))

            if de_text and en_text:
                if not isinstance(sent_tags, list):
                    sent_tags = data.get("tags", [])

                result_sentences.append({
                    "de": de_text,
                    "en": en_text,
                    "tags": sent_tags
                })
                print(f"   ✓ Example {i+1}: {len(sent_tags)} tags")
            else:
                print(f"   ✗ Example {i+1}: Missing example or translation")

        if not result_sentences:
            print(f"⚠ No valid examples found in enrichment response")
            return None

        # Extract metadata
        metadata = {
            "audio_url": data.get("audio_url"),
            "word_url": data.get("word_url"),
            "meanings": data.get("meanings", []),
            "tags": data.get("tags", [])
        }

        print(f"📊 Metadata extracted:")
        print(f"   Audio URL: {metadata['audio_url']}")
        print(f"   Word URL: {metadata['word_url']}")
        print(f"   Meanings: {len(metadata['meanings'])} items")
        print(f"   Tags: {metadata['tags']}")
        print(f"✓ Generated {len(result_sentences)} sentences + metadata from enrichment service")
        return (result_sentences, metadata)

    except Exception as e:
        print(f"❌ Enrichment service failed: {e}")
        return None


@app.post("/api/words/{word_id}/generate")
def api_generate_sentences(word_id: int, body: GenerateIn, request: Request):
    """Generate career-specific example sentences for a word via the AI provider
    and store them (shared, tagged with the career). Login required. Cached so the
    AI is called only once per (word, career); a cached hit costs no tokens. The
    user is charged TOKEN_COST_GENERATE once per (word, career)."""
    user = require_user(request)
    uid = user["id"]
    words = {w["id"]: w for w in db.list_words()}
    if word_id not in words:
        db.log_event("generate", "error", "word not found", uid, word_id, body.career)
        raise HTTPException(404, "word not found")
    cached = db.career_sentence_count(word_id, body.career) > 0
    # Charge the user once per (word, career) — whether the sentences are generated
    # now or already in the database — but never twice for the same one.
    charge_needed = not db.has_charged(uid, word_id, body.career)
    if charge_needed and db.get_tokens(uid) < TOKEN_COST_GENERATE:
        db.log_event("generate", "error", "out of tokens", uid, word_id, body.career)
        raise HTTPException(402, "You are out of tokens.")

    inserted = []
    if not cached:
        with _get_gen_lock(word_id, body.career):
            # Re-check inside the lock — another request may have just finished
            if db.career_sentence_count(word_id, body.career) == 0:
                # Try enrichment service first
                print(f"\n🎯 Generating sentences for word_id={word_id}, career={body.career}, level={body.level}")
                enrichment_result = _call_enrichment_service(words[word_id]["word"], body.career, body.level)
                pairs = None
                metadata = {}

                if enrichment_result:
                    print(f"✓ Enrichment service returned data")
                    sentences_with_tags, metadata = enrichment_result
                    print(f"   Got {len(sentences_with_tags)} sentences with tags")

                    # Update word with enriched metadata
                    if metadata.get("audio_url") or metadata.get("word_url"):
                        print(f"   Updating word metadata...")
                        with db.connect() as conn:
                            if metadata.get("audio_url"):
                                conn.execute("UPDATE words SET audio_url = ? WHERE id = ?", (metadata["audio_url"], word_id))
                                print(f"     ✓ audio_url updated")
                            if metadata.get("word_url"):
                                conn.execute("UPDATE words SET word_url = ? WHERE id = ?", (metadata["word_url"], word_id))
                                print(f"     ✓ word_url updated")

                    if metadata.get("tags"):
                        print(f"   Setting word tags: {metadata['tags']}")
                        db.set_tags(word_id, metadata["tags"])

                    # Add sentences with their tags
                    print(f"   Adding sentences with tags...")
                    inserted = db.add_career_sentences_with_tags(word_id, body.career, sentences_with_tags)
                    print(f"     ✓ {len(inserted)} sentences inserted")
                    pairs = None
                else:
                    print(f"⚠ Enrichment service failed, will fall back to AI provider")

                # Fall back to built-in AI provider if enrichment failed
                if not inserted:
                    print(f"📡 Enrichment service unavailable, falling back to AI provider")
                    provider = get_ai()
                    if not provider.available():
                        db.log_event("generate", "error", f"AI not available ({provider.name})", uid, word_id, body.career)
                        raise HTTPException(503, "AI sentence generation is not configured on this server.")
                    pairs = provider.generate_sentences(words[word_id]["word"], body.career, body.level, body.n)

                    if not pairs:
                        db.log_event("generate", "error", "No sentences generated from any provider", uid, word_id, body.career)
                        raise HTTPException(502, "Could not generate sentences from any provider.")

                    inserted = db.add_career_sentences(word_id, body.career, pairs)
            cached = True  # sentences now exist (either just generated or by the concurrent winner)

    tokens = user.get("tokens")
    if charge_needed:
        tokens = db.spend_tokens(uid, TOKEN_COST_GENERATE)
        if tokens is None:  # lost a race for the last tokens
            tokens = db.get_tokens(uid)
        db.record_charge(uid, word_id, body.career)
    db.log_event("generate", "cached" if cached else "generated",
                 f"{len(inserted)} sentence(s)", uid, word_id, body.career)
    return {"created": len(inserted), "cached": cached, "charged": charge_needed,
            "sentences": inserted, "tokens": tokens}


# ---- admin-only writes (words are curated by admins, not users) ----
@app.post("/api/words")
def api_add_word(body: WordIn, request: Request):
    require_admin(request)
    word_id, created = db.add_word(
        body.word, body.category,
        [(s.sentence_de, s.sentence_en) for s in body.sentences], body.level,
        lemma=body.lemma, pos=body.pos, article=body.article,
        audio_url=body.audio_url, word_url=body.word_url, image_url=body.image_url,
        unit_id=body.unit_id
    )
    # Add tags if provided
    print(f"🏷️  Setting tags for word_id={word_id}: {body.tags}")
    if body.tags:
        db.set_tags(word_id, body.tags)
        print(f"✓ Tags set successfully")
    else:
        print(f"⚠ No tags provided")
    # `created` is False when the word already existed and we merged sentences.
    return {"id": word_id, "created": created}


@app.post("/api/words/batch")
def api_add_words_batch(body: list[WordIn], request: Request):
    require_admin(request)
    if not body:
        raise HTTPException(400, "send a non-empty list of words")
    results = []
    for w in body:
        word_id, created = db.add_word(w.word, w.category,
                    [(s.sentence_de, s.sentence_en) for s in w.sentences], w.level,
                    lemma=w.lemma, pos=w.pos, article=w.article,
                    audio_url=w.audio_url, word_url=w.word_url, image_url=w.image_url,
                    unit_id=w.unit_id)
        if w.tags:
            db.set_tags(word_id, w.tags)
        results.append((word_id, created))
    ids = [wid for wid, _ in results]
    created = sum(1 for _, c in results if c)
    return {"ids": ids, "created": created, "merged": len(results) - created}


@app.post("/api/words/{word_id}/sentences")
def api_add_sentence(word_id: int, body: SentenceIn, request: Request):
    require_admin(request)
    sid = db.add_sentence(word_id, body.sentence_de, body.sentence_en)
    if sid is None:
        raise HTTPException(404, "word not found")
    return {"id": sid or None, "duplicate": sid == 0}


@app.delete("/api/words/{word_id}")
def api_delete_word(word_id: int, request: Request):
    require_admin(request)
    if not db.delete_word(word_id):
        raise HTTPException(404, "word not found")
    return {"ok": True}


@app.delete("/api/sentences/{sentence_id}")
def api_delete_sentence(sentence_id: int, request: Request):
    require_admin(request)
    if not db.delete_sentence(sentence_id):
        raise HTTPException(404, "sentence not found")
    return {"ok": True}


# ---- tokens ----
@app.get("/api/tokens")
def api_get_tokens(request: Request):
    user = require_user(request)
    return {"tokens": db.get_tokens(user["id"])}


@app.post("/api/tokens/grant")
def api_grant_tokens(body: GrantTokensIn, request: Request):
    """Admin top-up: add tokens to a user by email."""
    require_admin(request)
    target = db.get_user_by_email(body.email.strip())
    if not target:
        raise HTTPException(404, "user not found")
    return {"email": target.get("email"), "tokens": db.grant_tokens(target["id"], body.amount)}


# ---- token packages (admin-defined) ----
def _package_public(p):
    return {"id": p["id"], "tokens": p["tokens"], "price": p["price_cents"] / 100,
            "price_cents": p["price_cents"], "currency": p["currency"],
            "active": bool(p["active"]), "position": p["position"]}


@app.get("/api/packages")
def api_packages(request: Request):
    """Active packages for the buy UI (signed-in users)."""
    require_user(request)
    return [_package_public(p) for p in db.list_packages(active_only=True)]


@app.get("/api/admin/packages")
def api_admin_packages(request: Request):
    require_admin(request)
    return [_package_public(p) for p in db.list_packages()]


@app.post("/api/packages")
def api_save_package(body: PackageIn, request: Request):
    require_admin(request)
    pid = db.save_package(body.tokens, round(body.price * 100), body.currency.upper(),
                          body.active, body.position, body.id)
    return {"id": pid}


@app.delete("/api/packages/{pkg_id}")
def api_delete_package(pkg_id: int, request: Request):
    require_admin(request)
    if not db.delete_package(pkg_id):
        raise HTTPException(404, "package not found")
    return {"ok": True}


# ---- PayPal checkout (buy tokens) ----
@app.post("/api/paypal/create-order")
def api_paypal_create(body: CreateOrderIn, request: Request):
    require_user(request)
    if not paypal.enabled():
        raise HTTPException(503, "Payments are not configured on this server.")
    pkg = db.get_package(body.package_id)
    if not pkg or not pkg["active"]:
        raise HTTPException(404, "package not available")
    amount = f"{pkg['price_cents'] / 100:.2f}"
    try:
        order_id = paypal.create_order(amount, pkg["currency"], f"pkg-{pkg['id']}")
    except Exception:
        raise HTTPException(502, "Could not start the PayPal checkout.")
    return {"order_id": order_id}


@app.post("/api/paypal/capture-order")
def api_paypal_capture(body: CaptureOrderIn, request: Request):
    user = require_user(request)
    if not paypal.enabled():
        raise HTTPException(503, "Payments are not configured on this server.")
    pkg = db.get_package(body.package_id)
    if not pkg:
        raise HTTPException(404, "package not available")
    try:
        ok, value, currency = paypal.capture_order(body.order_id)
    except Exception:
        raise HTTPException(502, "Could not complete the PayPal payment.")
    # Verify PayPal charged exactly the package price before crediting tokens.
    expected = f"{pkg['price_cents'] / 100:.2f}"
    if not ok or value != expected or (currency or "").upper() != pkg["currency"].upper():
        db.log_event("purchase", "error", f"capture mismatch order={body.order_id}", user["id"])
        raise HTTPException(400, "Payment could not be verified.")
    tokens = db.record_purchase(user["id"], pkg["id"], pkg["tokens"], pkg["price_cents"],
                                pkg["currency"], "paypal", body.order_id)
    if tokens is None:  # already processed this order
        return {"tokens": db.get_tokens(user["id"]), "already": True}
    db.log_event("purchase", "ok", f"+{pkg['tokens']} tokens for {expected} {pkg['currency']}",
                 user["id"])
    return {"tokens": tokens, "added": pkg["tokens"]}


# ---- private per-user notes ----
@app.get("/api/notes")
def api_get_notes(request: Request):
    user = require_user(request)
    return db.get_notes(user["id"])


@app.put("/api/notes/{word_id}")
def api_put_note(word_id: int, body: NoteIn, request: Request):
    user = require_user(request)
    if not db.save_note(user["id"], word_id, body.note):
        raise HTTPException(404, "word not found")
    return {"ok": True}


@app.get("/api/categories")
def api_categories():
    return db.categories()


# --------------------------------------------------------------------------
# grammar topics (shared, read-focused)
# --------------------------------------------------------------------------
@app.get("/grammar")
def grammar_page():
    return FileResponse(STATIC_DIR / "grammar.html")


@app.get("/api/grammar")
def api_grammar_list():
    return db.list_grammar()


@app.get("/api/grammar/{slug}")
def api_grammar_get(slug: str):
    topic = db.get_grammar(slug)
    if not topic:
        raise HTTPException(404, "grammar topic not found")
    return topic


@app.post("/api/grammar")
def api_grammar_add(body: GrammarIn):
    gid = db.add_grammar(body.title, body.body, body.category, body.position)
    return {"id": gid}


@app.delete("/api/grammar/{grammar_id}")
def api_grammar_delete(grammar_id: int):
    if not db.delete_grammar(grammar_id):
        raise HTTPException(404, "grammar topic not found")
    return {"ok": True}


# --------------------------------------------------------------------------
# readings (admin-posted stories; unlocked client-side as users progress)
# --------------------------------------------------------------------------
@app.get("/api/readings")
def api_readings_list():
    return db.list_readings()


@app.get("/api/readings/{reading_id}")
def api_reading_get(reading_id: int):
    r = db.get_reading(reading_id)
    if not r:
        raise HTTPException(404, "reading not found")
    return r


@app.post("/api/readings")
def api_reading_add(body: ReadingIn, request: Request):
    require_admin(request)
    rid = db.add_reading(body.title, body.body, body.level, body.position, body.id,
                         normalize_audio_url(body.audio_url))
    return {"id": rid}


_AUDIO_EXT = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
              "audio/x-wav": ".wav", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
              "audio/x-m4a": ".m4a", "audio/aac": ".aac", "audio/webm": ".webm"}
_MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB


@app.post("/api/readings/{reading_id}/audio")
async def api_reading_upload_audio(reading_id: int, request: Request, file: UploadFile = File(...)):
    """Upload an audio file for a reading; the app stores and serves it directly."""
    require_admin(request)
    if not db.get_reading(reading_id):
        raise HTTPException(404, "reading not found")
    ext = _AUDIO_EXT.get((file.content_type or "").lower()) \
        or os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".webm"}:
        raise HTTPException(400, "Unsupported audio type. Use mp3, m4a, wav, ogg, aac or webm.")
    data = await file.read()
    if len(data) > _MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio file too large (max 25 MB).")
    dest_dir = MEDIA_DIR / "readings"
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"{reading_id}{ext}"
    (dest_dir / name).write_bytes(data)
    url = f"/media/readings/{name}"
    db.set_reading_audio(reading_id, url)
    return {"ok": True, "audio_url": url}


@app.get("/media/{path:path}")
def serve_media(path: str):
    # Only serve files that actually live under MEDIA_DIR (no path traversal).
    target = (MEDIA_DIR / path).resolve()
    if not str(target).startswith(str(MEDIA_DIR.resolve())) or not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(target)


@app.delete("/api/readings/{reading_id}")
def api_reading_delete(reading_id: int, request: Request):
    require_admin(request)
    if not db.delete_reading(reading_id):
        raise HTTPException(404, "reading not found")
    return {"ok": True}


# --------------------------------------------------------------------------
# per-user progress (logged-in only; guests keep progress in the browser)
# --------------------------------------------------------------------------
@app.get("/api/progress")
def api_get_progress(request: Request):
    user = require_user(request)
    return db.get_progress(user["id"])


@app.put("/api/progress/{word_id}")
def api_put_progress(word_id: int, body: ProgressIn, request: Request):
    user = require_user(request)
    ok = db.upsert_progress(
        user["id"], word_id, body.reps, body.interval, body.ease, body.lapses, body.due
    )
    if not ok:
        raise HTTPException(404, "word not found")
    return {"ok": True}


# --------------------------------------------------------------------------
# learner profile + lesson learning state (logged-in only; guests use browser)
# --------------------------------------------------------------------------
@app.get("/api/profile")
def api_get_profile(request: Request):
    user = require_user(request)
    return db.get_profile(user["id"])


@app.put("/api/profile")
def api_put_profile(body: ProfileIn, request: Request):
    user = require_user(request)
    db.save_profile(user["id"], body.career, body.level, body.daily_goal, body.location)
    return {"ok": True}


@app.get("/api/learning")
def api_get_learning(request: Request):
    user = require_user(request)
    return db.get_learning(user["id"])


@app.put("/api/learning")
def api_put_learning(body: LearningIn, request: Request):
    user = require_user(request)
    db.save_learning(user["id"], body.learned, body.wrong)
    return {"ok": True}


@app.get("/api/careers")
def api_careers(request: Request):
    return db.career_suggestions()


@app.get("/api/score")
def api_score(request: Request):
    user = require_user(request)
    return db.get_user_score(user["id"])


@app.get("/api/inbox")
def api_inbox(request: Request):
    user = require_user(request)
    return db.get_inbox(user["id"])


@app.post("/api/inbox/{message_id}/read")
def api_inbox_read(message_id: int, request: Request):
    user = require_user(request)
    db.mark_read(user["id"], message_id)
    return {"ok": True}


@app.post("/api/inbox/read-all")
def api_inbox_read_all(request: Request):
    user = require_user(request)
    db.mark_read(user["id"])
    return {"ok": True}


class UnitIn(BaseModel):
    title: str = Field(min_length=1)
    level: str = "B1"
    token_cost: int = Field(default=0, ge=0)
    quiz_score: int = Field(default=6, ge=0)
    position: int = 0


class UnitWordsIn(BaseModel):
    word_ids: list[int] = []


@app.get("/api/units")
def api_list_units(request: Request):
    user = current_user(request)
    uid = user["id"] if user else None
    return db.list_units(user_id=uid)


@app.post("/api/units")
def api_create_unit(body: UnitIn, request: Request):
    require_admin(request)
    uid = db.save_unit(body.title, body.level, body.token_cost, body.position, quiz_score=body.quiz_score)
    return db.get_unit(uid)


@app.put("/api/units/{unit_id}")
def api_update_unit(unit_id: int, body: UnitIn, request: Request):
    require_admin(request)
    db.save_unit(body.title, body.level, body.token_cost, body.position, unit_id=unit_id, quiz_score=body.quiz_score)
    return db.get_unit(unit_id)


@app.delete("/api/units/{unit_id}")
def api_delete_unit(unit_id: int, request: Request):
    require_admin(request)
    db.delete_unit(unit_id)
    return {"ok": True}


@app.put("/api/units/{unit_id}/words")
def api_set_unit_words(unit_id: int, body: UnitWordsIn, request: Request):
    require_admin(request)
    db.set_unit_words(unit_id, body.word_ids)
    return {"ok": True}


@app.post("/api/units/{unit_id}/unlock")
def api_unlock_unit(unit_id: int, request: Request):
    user = require_user(request)
    result = db.unlock_unit(user["id"], unit_id)
    if not result.get("ok"):
        reason = result.get("reason", "")
        if reason == "prev_incomplete":
            raise HTTPException(409, "Finish the previous unit first.")
        if reason == "insufficient":
            raise HTTPException(402, "Not enough tokens.")
        raise HTTPException(400, reason)
    return result


@app.post("/api/units/{unit_id}/score")
def api_unit_score(unit_id: int, request: Request):
    user = require_user(request)
    awarded = db.award_unit_score(user["id"], unit_id)
    return {"awarded": awarded, "score": db.get_user_score(user["id"])}


@app.post("/api/units/{unit_id}/complete")
def api_unit_complete(unit_id: int, request: Request):
    """Mark a unit as complete and unlock the next unit."""
    user = require_user(request)
    user_id = user["id"]

    # Get current unit first
    current_unit = db.get_unit(unit_id)
    if not current_unit:
        raise HTTPException(404, "Unit not found")

    # Mark current unit as completed (unlock state)
    db.unlock_unit_for_user(user_id, unit_id)

    # Award quiz score for completion
    score_awarded = db.award_unit_score(user_id, unit_id)

    # Find and unlock next unit
    all_units = db.list_units(user_id=user_id)  # Refresh units AFTER marking complete
    print(f"📍 Current unit position: {current_unit['position']}")
    print(f"📋 Looking for unit with position > {current_unit['position']}")
    next_unit = next((u for u in all_units if u["position"] > current_unit["position"]), None)
    if next_unit:
        print(f"🔓 Found next unit: {next_unit['id']} (position {next_unit['position']})")
        db.unlock_unit_for_user(user_id, next_unit["id"])
        print(f"✅ Unit {unit_id} marked complete, Unit {next_unit['id']} auto-unlocked for user {user_id}")
    else:
        print(f"✅ Unit {unit_id} marked complete - no next unit (last unit)")

    return {
        "unit_id": unit_id,
        "completed": True,
        "score_awarded": score_awarded,
        "next_unit_id": next_unit["id"] if next_unit else None,
        "next_unit_name": next_unit["title"] if next_unit else None
    }


class ReadingIn(BaseModel):
    level: str = "B1"
    words: list[str] = []
    unit_id: int | None = None

@app.post("/api/reading")
def api_reading(body: ReadingIn):
    """Generate a ~80 word reading that includes the given words at the specified level.
    Saves to database and reuses if reading already exists for this unit."""
    import json
    import re
    import requests

    print(f"\n🎯 /api/reading called with: level={body.level}, words={len(body.words)}, unit_id={body.unit_id}")

    if not body.words:
        raise HTTPException(400, "At least one word is required")

    words_str = ", ".join(body.words)
    level = (body.level or "B1").upper()

    # Check if reading already exists for this unit
    if body.unit_id:
        try:
            existing = db.get_reading_by_unit(body.unit_id)
            if existing:
                print(f"📚 Found existing reading for unit {body.unit_id}: {existing['title']}")
                return {
                    "id": existing["id"],
                    "level": existing["level"],
                    "words": body.words,
                    "title": existing["title"],
                    "text": existing["body"]
                }
        except Exception as e:
            print(f"⚠️ Could not check for existing reading: {e}")

    # Try enrichment service first if enabled (with short timeout)
    if ENRICHMENT_ENABLED:
        try:
            resp = requests.post(
                f"{ENRICHMENT_ENDPOINT}/reading",
                json={"level": level, "words": body.words},
                timeout=120  # Increased from 5s for AI content generation
            )
            if resp.status_code == 200:
                data = resp.json()
                print(f"📚 Got reading from enrichment service")
                return {
                    "level": level,
                    "words": body.words,
                    "title": data.get("title", "Reading"),
                    "text": data.get("text", "")
                }
        except Exception:
            pass  # Silently fail and fall back to AI provider

    # Fall back to configured AI provider (Claude, Gemini, or Ollama)
    prompt = f"""Create a brief, engaging German reading (~80 words) at CEFR level {level}.
The reading must naturally include these key words: {words_str}

Guidelines for level {level}:
- A1: Use only the most common everyday words, present tense, very short sentences
- A2: Use common everyday words, simple sentences, present/past tense
- B1: Natural vocabulary and grammar, can use subordinate clauses
- B2: Professional and everyday vocabulary, complex sentences acceptable
- C1: Advanced vocabulary and complex structures acceptable
- C2: Sophisticated, literary German acceptable

Respond with ONLY a JSON object in this exact shape, no prose:
{{"title": "<Short engaging title>", "text": "<The German reading text>"}}"""

    try:
        ai_provider = get_ai()
        if not ai_provider.available():
            raise HTTPException(503, "AI provider not available")

        text = None
        provider_name = getattr(ai_provider, 'name', 'unknown')

        # Support different provider types
        if hasattr(ai_provider, '_generate'):
            # Ollama provider
            print(f"📖 Reading: Using Ollama model '{ai_provider.model}'")
            text = ai_provider._generate(prompt)
            print(f"✅ Reading generated via Ollama ({len(text)} chars)")
        elif hasattr(ai_provider, 'api_key') and hasattr(ai_provider, '_client_or_none'):
            # Claude provider
            print(f"📖 Reading: Using Claude model '{ai_provider.model}'")
            import anthropic
            client = ai_provider._client_or_none()
            resp = client.messages.create(
                model=ai_provider.model,
                max_tokens=500,
                system="You are a German language teacher creating engaging readings for learners.",
                messages=[{"role": "user", "content": prompt}]
            )
            text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
            print(f"✅ Reading generated via Claude ({len(text)} chars)")
        else:
            raise HTTPException(503, f"Reading requires Claude, Gemini, or Ollama provider (got {provider_name})")

        if not text or text.strip() == "":
            raise HTTPException(500, "Empty response from AI provider")

        # Parse JSON response
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)

        data = json.loads(text)
        title = data.get("title", "Reading")
        reading_text = data.get("text", "")

        # Save to database (with or without unit_id)
        reading_id = None
        print(f"📝 Attempting to save reading: unit_id={body.unit_id}, title='{title}'")
        try:
            reading_id = db.save_reading(
                title=title,
                body=reading_text,
                level=level,
                unit_id=body.unit_id  # Can be None for free lessons
            )
            print(f"✅ Saved reading to database with ID {reading_id}")
        except Exception as e:
            print(f"❌ Error saving reading to database: {e}")
            import traceback
            traceback.print_exc()

        return {
            "id": reading_id,
            "level": level,
            "words": body.words,
            "title": title,
            "text": reading_text
        }
    except json.JSONDecodeError as e:
        print(f"❌ JSON parse error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Invalid JSON from AI: {str(e)}")
    except Exception as e:
        print(f"❌ Reading generation error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to generate reading: {str(e)}")

@app.get("/api/events")
async def api_events(request: Request):
    require_user(request)

    async def stream():
        # Keep the connection alive with periodic comments; no events to send yet.
        while True:
            if await request.is_disconnected():
                break
            yield ": keep-alive\n\n"
            import asyncio
            await asyncio.sleep(30)

    return StreamingResponse(stream(), media_type="text/event-stream")
