"""FastAPI backend for the German DevOps flashcard app.

Words and sentences are shared by everyone. Spaced-repetition scheduling runs
in the browser; this server just serves the shared deck and (for logged-in
users) persists per-user progress. Google login is optional.
"""
import os
import re
import secrets
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

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

app = FastAPI(title="German DevOps Flashcards")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")

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
    return db.get_user(uid) if uid else None


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
    token = await oauth.google.authorize_access_token(request)
    info = token.get("userinfo") or {}
    if not info.get("sub"):
        raise HTTPException(400, "Could not read Google profile.")
    user = db.upsert_user(
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
                provider = get_ai()
                if not provider.available():
                    db.log_event("generate", "error", "AI not configured", uid, word_id, body.career)
                    raise HTTPException(503, "AI sentence generation is not configured on this server.")
                pairs = provider.generate_sentences(words[word_id]["word"], body.career, body.level, body.n)
                if not pairs:
                    db.log_event("generate", "error", "AI returned no sentences", uid, word_id, body.career)
                    raise HTTPException(502, "The AI provider returned no usable sentences.")
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
    )
    # `created` is False when the word already existed and we merged sentences.
    return {"id": word_id, "created": created}


@app.post("/api/words/batch")
def api_add_words_batch(body: list[WordIn], request: Request):
    require_admin(request)
    if not body:
        raise HTTPException(400, "send a non-empty list of words")
    results = [
        db.add_word(w.word, w.category,
                    [(s.sentence_de, s.sentence_en) for s in w.sentences], w.level)
        for w in body
    ]
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
    db.save_profile(user["id"], body.career, body.level, body.daily_goal)
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
