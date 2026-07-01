"""SQLite storage.

Data model:
  users      - people who logged in with Google (optional).
  words      - shared vocabulary items (visible to everyone).
  sentences  - one or more example sentences (DE/EN) belonging to a word.
  progress   - per-user spaced-repetition state for a word.

Scheduling (SM-2) and "what is due" live in the browser so that guests (no
account) and logged-in users behave identically: guests keep progress in
localStorage, logged-in users keep it here in the `progress` table.
"""
import base64
import hashlib
import hmac
import os
import re
import sqlite3
from pathlib import Path

# Override with DB_PATH (e.g. a mounted volume in Docker); defaults to alongside
# this file for local runs.
DB_PATH = Path(os.getenv("DB_PATH") or (Path(__file__).parent / "flashcards.db"))

# Tokens (credits) each new account starts with. Spending happens when a user
# triggers a paid service (e.g. AI sentence generation).
START_TOKENS = int(os.getenv("START_TOKENS", "200"))

SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        sub           TEXT NOT NULL UNIQUE,
        email         TEXT,
        name          TEXT,
        picture       TEXT,
        password_hash TEXT,
        tokens        INTEGER NOT NULL DEFAULT 200,
        ref_code      TEXT UNIQUE,
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    -- Referrals: one row per invited user (rewarded once). The referrer earns tokens.
    CREATE TABLE IF NOT EXISTS referrals (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        invited_id  INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        code        TEXT,
        tokens      INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS words (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        word        TEXT NOT NULL,
        topic       TEXT NOT NULL DEFAULT 'general',
        level       TEXT NOT NULL DEFAULT 'B1',
        unit_id     INTEGER,
        lemma       TEXT,
        pos         TEXT,
        article     TEXT,
        audio_url   TEXT,
        word_url    TEXT,
        image_url   TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    -- Admin-built unit packs: a named group of words at a level, with a token
    -- cost to unlock. Users finish the previous unit, then spend tokens to open.
    CREATE TABLE IF NOT EXISTS units (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        level       TEXT NOT NULL DEFAULT 'B1',
        token_cost  INTEGER NOT NULL DEFAULT 0,
        position    INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    -- One row per (user, unit) the user has paid to unlock.
    CREATE TABLE IF NOT EXISTS unit_unlocks (
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        unit_id     INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
        tokens      INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, unit_id)
    );
    CREATE TABLE IF NOT EXISTS sentences (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id     INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        sentence_de TEXT NOT NULL,
        sentence_en TEXT NOT NULL,
        career      TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_sentences_word ON sentences(word_id);
    CREATE TABLE IF NOT EXISTS sentence_tags (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sentence_id INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
        tag         TEXT NOT NULL,
        UNIQUE(sentence_id, tag)
    );
    CREATE INDEX IF NOT EXISTS idx_sentence_tags_tag ON sentence_tags(tag);
    CREATE TABLE IF NOT EXISTS notes (
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        word_id     INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        note        TEXT NOT NULL DEFAULT '',
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, word_id)
    );
    CREATE TABLE IF NOT EXISTS progress (
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        word_id     INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        reps        INTEGER NOT NULL DEFAULT 0,
        interval    INTEGER NOT NULL DEFAULT 0,
        ease        REAL    NOT NULL DEFAULT 2.5,
        lapses      INTEGER NOT NULL DEFAULT 0,
        due         TEXT    NOT NULL,
        updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, word_id)
    );
    CREATE TABLE IF NOT EXISTS grammar (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        slug        TEXT NOT NULL UNIQUE,
        topic    TEXT NOT NULL DEFAULT 'general',
        body        TEXT NOT NULL,
        position    INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS profiles (
        user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        career      TEXT NOT NULL DEFAULT 'general',
        level       TEXT NOT NULL DEFAULT 'B1',
        daily_goal  INTEGER NOT NULL DEFAULT 10,
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS learning (
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        word_id     INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        learned     INTEGER NOT NULL DEFAULT 0,
        wrong       INTEGER NOT NULL DEFAULT 0,
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, word_id)
    );
    -- One row per (user, word, career) that the user has already paid tokens for,
    -- so each user is charged once per word/career — whether the sentences were
    -- freshly generated or served from cache — but never charged twice.
    CREATE TABLE IF NOT EXISTS token_charges (
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        word_id     INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        career      TEXT NOT NULL,
        charged_at  TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, word_id, career)
    );
    -- Admin-posted reading stories. Unlocked step by step as a user completes
    -- units of words (gating computed client-side from learning progress).
    CREATE TABLE IF NOT EXISTS readings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        level       TEXT NOT NULL DEFAULT 'B1',
        body        TEXT NOT NULL,
        audio_url   TEXT,
        position    INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    -- Append-only log of AI generation calls (and their errors) for the admin
    -- dashboard. status: 'generated' | 'cached' | 'error'.
    CREATE TABLE IF NOT EXISTS api_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        action      TEXT NOT NULL,
        status      TEXT NOT NULL,
        detail      TEXT,
        word_id     INTEGER,
        career      TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_api_log_created ON api_log(created_at);
    -- Simple key/value app settings managed from the admin dashboard (e.g. the AI
    -- provider, models and API keys). These override the matching env vars.
    CREATE TABLE IF NOT EXISTS settings (
        key         TEXT PRIMARY KEY,
        value       TEXT,
        updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    -- Admin-defined token packages users can buy (price stored in cents).
    CREATE TABLE IF NOT EXISTS token_packages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        tokens      INTEGER NOT NULL,
        price_cents INTEGER NOT NULL,
        currency    TEXT NOT NULL DEFAULT 'EUR',
        active      INTEGER NOT NULL DEFAULT 1,
        position    INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    -- Request header info captured when a user starts a session (login/signup).
    CREATE TABLE IF NOT EXISTS access_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        event       TEXT,
        ip          TEXT,
        user_agent  TEXT,
        language    TEXT,
        referer     TEXT,
        path        TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_access_created ON access_log(created_at);
    -- Completed token purchases (audit + revenue).
    CREATE TABLE IF NOT EXISTS purchases (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
        package_id      INTEGER,
        tokens          INTEGER NOT NULL,
        price_cents     INTEGER NOT NULL,
        currency        TEXT NOT NULL DEFAULT 'EUR',
        provider        TEXT NOT NULL DEFAULT 'paypal',
        provider_ref    TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS companies (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        email         TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        contact_name  TEXT,
        contact_phone TEXT,
        approved      INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS advertisements (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id    INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        title         TEXT NOT NULL,
        description   TEXT NOT NULL,
        image_url     TEXT,
        image_type    TEXT,
        approved      INTEGER NOT NULL DEFAULT 0,
        active        INTEGER NOT NULL DEFAULT 1,
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS ad_tags (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ad_id         INTEGER NOT NULL REFERENCES advertisements(id) ON DELETE CASCADE,
        tag           TEXT NOT NULL,
        UNIQUE(ad_id, tag)
    );
    CREATE INDEX IF NOT EXISTS idx_ad_tags_tag ON ad_tags(tag);
    CREATE TABLE IF NOT EXISTS api_tokens (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        token         TEXT NOT NULL UNIQUE,
        name          TEXT,
        last_used_at  TEXT,
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_api_tokens_token ON api_tokens(token);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Ensure the schema exists on every connection so the app self-heals even
    # if flashcards.db is deleted while the server is running.
    conn.executescript(SCHEMA)
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


# --------------------------------------------------------------------------
# app settings (key/value, managed from the dashboard; override env vars)
# --------------------------------------------------------------------------
def get_setting(key, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row and row["value"] not in (None, "") else default


def set_setting(key, value):
    with connect() as conn:
        conn.execute(
            """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')""",
            (key, value),
        )


def _migrate(conn):
    """Additive migrations for databases created by older versions."""
    ucols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if ucols and "password_hash" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if ucols and "tokens" not in ucols:
        conn.execute(f"ALTER TABLE users ADD COLUMN tokens INTEGER NOT NULL DEFAULT {START_TOKENS}")
    if ucols and "ref_code" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN ref_code TEXT")
    scols = [r["name"] for r in conn.execute("PRAGMA table_info(sentences)").fetchall()]
    if scols and "career" not in scols:
        conn.execute("ALTER TABLE sentences ADD COLUMN career TEXT")
    wcols = [r["name"] for r in conn.execute("PRAGMA table_info(words)").fetchall()]
    if wcols and "level" not in wcols:
        conn.execute("ALTER TABLE words ADD COLUMN level TEXT NOT NULL DEFAULT 'B1'")
    if wcols and "unit_id" not in wcols:
        conn.execute("ALTER TABLE words ADD COLUMN unit_id INTEGER")
    # Legacy `url` held the pronunciation audio link; rename it to audio_url.
    if wcols and "url" in wcols and "audio_url" not in wcols:
        conn.execute("ALTER TABLE words RENAME COLUMN url TO audio_url")
        wcols = [r["name"] for r in conn.execute("PRAGMA table_info(words)").fetchall()]
    for col in ("lemma", "pos", "article", "audio_url", "word_url", "image_url"):
        if wcols and col not in wcols:
            conn.execute(f"ALTER TABLE words ADD COLUMN {col} TEXT")
    # Rename category → topic in words table
    wcols = [r["name"] for r in conn.execute("PRAGMA table_info(words)").fetchall()]
    if wcols and "category" in wcols and "topic" not in wcols:
        conn.execute("ALTER TABLE words RENAME COLUMN category TO topic")
    # Rename category → topic in grammar table
    gcols = [r["name"] for r in conn.execute("PRAGMA table_info(grammar)").fetchall()]
    if gcols and "category" in gcols and "topic" not in gcols:
        conn.execute("ALTER TABLE grammar RENAME COLUMN category TO topic")
    rcols = [r["name"] for r in conn.execute("PRAGMA table_info(readings)").fetchall()]
    if rcols and "audio_url" not in rcols:
        conn.execute("ALTER TABLE readings ADD COLUMN audio_url TEXT")
    if rcols and "unit_id" not in rcols:
        conn.execute("ALTER TABLE readings ADD COLUMN unit_id INTEGER REFERENCES units(id) ON DELETE CASCADE")
    ucols2 = [r["name"] for r in conn.execute("PRAGMA table_info(units)").fetchall()]
    if ucols2 and "quiz_score" not in ucols2:
        conn.execute("ALTER TABLE units ADD COLUMN quiz_score INTEGER NOT NULL DEFAULT 6")
    if ucols and "call_ready" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN call_ready INTEGER NOT NULL DEFAULT 0")
    pcols = [r["name"] for r in conn.execute("PRAGMA table_info(profiles)").fetchall()]
    if pcols and "location" not in pcols:
        conn.execute("ALTER TABLE profiles ADD COLUMN location TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS call_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        caller_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        callee_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        tokens_each INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    # per-user score log: one row per (user, unit) pass — later passes don't re-award
    conn.execute("""CREATE TABLE IF NOT EXISTS unit_scores (
        user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        unit_id   INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
        score     INTEGER NOT NULL DEFAULT 0,
        earned_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, unit_id)
    )""")
    # call score rewards — separate from unit_scores to avoid FK constraint on units
    conn.execute("""CREATE TABLE IF NOT EXISTS call_scores (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        score      INTEGER NOT NULL DEFAULT 0,
        call_log_id INTEGER REFERENCES call_logs(id),
        earned_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    # tags per word
    conn.execute("""CREATE TABLE IF NOT EXISTS word_tags (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        tag     TEXT NOT NULL,
        UNIQUE(word_id, tag)
    )""")
    # multiple meanings per word
    conn.execute("""CREATE TABLE IF NOT EXISTS word_meanings (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id    INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
        meaning    TEXT NOT NULL,
        position   INTEGER NOT NULL DEFAULT 0
    )""")
    # inbox messages
    conn.execute("""CREATE TABLE IF NOT EXISTS inbox (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        subject    TEXT NOT NULL,
        body       TEXT NOT NULL,
        icon       TEXT NOT NULL DEFAULT '📬',
        read       INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")


# --------------------------------------------------------------------------
# passwords (PBKDF2-HMAC-SHA256, standard library only)
# --------------------------------------------------------------------------
_PBKDF2_ITERATIONS = 200_000


def hash_password(password):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password, stored):
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(iters)
        )
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, AttributeError, TypeError):
        return False


# --------------------------------------------------------------------------
# users
# --------------------------------------------------------------------------
def upsert_user(sub, email, name, picture):
    """Create or update a user by their Google subject id. Returns (row, created)
    where `created` is True only when a brand-new user row was inserted."""
    with connect() as conn:
        existed = conn.execute("SELECT 1 FROM users WHERE sub = ?", (sub,)).fetchone() is not None
        conn.execute(
            """INSERT INTO users (sub, email, name, picture, tokens) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(sub) DO UPDATE SET email=excluded.email,
                   name=excluded.name, picture=excluded.picture""",
            (sub, email, name, picture, START_TOKENS),
        )
        row = conn.execute("SELECT * FROM users WHERE sub = ?", (sub,)).fetchone()
        return dict(row), (not existed)


def get_user(user_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(email) = LOWER(?) LIMIT 1", (email.strip(),)
        ).fetchone()
        return dict(row) if row else None


def create_local_user(email, password, name=None):
    """Create an email/password account. Raises ValueError if the email is taken.
    Local accounts use sub = 'local:<email>' so they share the unique `sub` key
    with Google accounts. Returns the new user row."""
    email = email.strip()
    if get_user_by_email(email):
        raise ValueError("email already registered")
    sub = "local:" + email.lower()
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (sub, email, name, password_hash, tokens) VALUES (?, ?, ?, ?, ?)",
                (sub, email, (name or None), hash_password(password), START_TOKENS),
            )
        except sqlite3.IntegrityError:
            raise ValueError("email already registered")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def authenticate(email, password):
    """Return the user row if email+password match a local account, else None."""
    user = get_user_by_email(email)
    if user and user.get("password_hash") and verify_password(password, user["password_hash"]):
        return user
    return None


# --------------------------------------------------------------------------
# tokens (credits)
# --------------------------------------------------------------------------
def get_tokens(user_id):
    with connect() as conn:
        row = conn.execute("SELECT tokens FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["tokens"] if row else 0


def spend_tokens(user_id, amount):
    """Atomically deduct `amount` tokens. Returns the new balance, or None if the
    user does not have enough (no change is made in that case)."""
    amount = max(0, int(amount))
    with connect() as conn:
        cur = conn.execute(
            "UPDATE users SET tokens = tokens - ? WHERE id = ? AND tokens >= ?",
            (amount, user_id, amount),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT tokens FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["tokens"] if row else None


def grant_tokens(user_id, amount):
    """Add tokens to a user (e.g. a top-up). Returns the new balance."""
    with connect() as conn:
        conn.execute("UPDATE users SET tokens = tokens + ? WHERE id = ?", (int(amount), user_id))
        row = conn.execute("SELECT tokens FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["tokens"] if row else None


# --------------------------------------------------------------------------
# referrals (invite friends → earn tokens)
# --------------------------------------------------------------------------
def _gen_ref_code():
    return base64.urlsafe_b64encode(os.urandom(6)).decode().rstrip("=")


def ensure_ref_code(user_id):
    """Return the user's referral code, generating a unique one on first use."""
    with connect() as conn:
        row = conn.execute("SELECT ref_code FROM users WHERE id = ?", (user_id,)).fetchone()
        if row and row["ref_code"]:
            return row["ref_code"]
        for _ in range(10):
            code = _gen_ref_code()
            try:
                conn.execute("UPDATE users SET ref_code = ? WHERE id = ?", (code, user_id))
                return code
            except sqlite3.IntegrityError:
                continue
    return None


def get_user_by_ref_code(code):
    if not code:
        return None
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE ref_code = ?", (code.strip(),)).fetchone()
        return dict(row) if row else None


def apply_referral(code, invited_id, tokens):
    """Credit the referrer (owner of `code`) for inviting `invited_id`, once.
    Returns the referrer id if a reward was granted, else None."""
    referrer = get_user_by_ref_code(code)
    if not referrer or referrer["id"] == invited_id:
        return None
    with connect() as conn:
        # one reward per invited user
        if conn.execute("SELECT 1 FROM referrals WHERE invited_id = ?", (invited_id,)).fetchone():
            return None
        conn.execute(
            "INSERT INTO referrals (referrer_id, invited_id, code, tokens) VALUES (?, ?, ?, ?)",
            (referrer["id"], invited_id, code, int(tokens)),
        )
        conn.execute("UPDATE users SET tokens = tokens + ? WHERE id = ?", (int(tokens), referrer["id"]))
    return referrer["id"]


def referral_stats(user_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(tokens),0) AS earned FROM referrals WHERE referrer_id = ?",
            (user_id,),
        ).fetchone()
        return {"invited": row["n"], "earned": row["earned"]}


def leaderboard(user_id=None, limit=10):
    """Top learners by words learned (earned via quizzes). Also returns the
    requesting user's own rank/count so they can see where they stand."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT u.id, u.name, u.email, u.call_ready, COUNT(*) AS learned
               FROM users u JOIN learning l ON l.user_id = u.id AND l.learned = 1
               GROUP BY u.id HAVING learned > 0
               ORDER BY learned DESC, u.id ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        top = [{"id": r["id"], "name": r["name"], "email": r["email"],
                "learned": r["learned"], "call_ready": bool(r["call_ready"])}
               for r in rows]
        me = None
        if user_id is not None:
            mine = conn.execute(
                "SELECT COUNT(*) AS c FROM learning WHERE user_id = ? AND learned = 1",
                (user_id,),
            ).fetchone()["c"]
            ahead = conn.execute(
                """SELECT COUNT(*) AS a FROM
                   (SELECT user_id, COUNT(*) AS n FROM learning WHERE learned = 1 GROUP BY user_id)
                   WHERE n > ?""",
                (mine,),
            ).fetchone()["a"]
            me = {"learned": mine, "rank": (ahead + 1) if mine > 0 else None}
        return {"top": top, "me": me}


def has_charged(user_id, word_id, career):
    """Has this user already paid tokens for this (word, career)?"""
    with connect() as conn:
        return conn.execute(
            "SELECT 1 FROM token_charges WHERE user_id = ? AND word_id = ? AND career = ?",
            (user_id, word_id, career),
        ).fetchone() is not None


def record_charge(user_id, word_id, career):
    """Mark that this user has paid for this (word, career) so they aren't charged again."""
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO token_charges (user_id, word_id, career) VALUES (?, ?, ?)",
            (user_id, word_id, career),
        )


# --------------------------------------------------------------------------
# words & sentences (shared by everyone)
# --------------------------------------------------------------------------
def _insert_sentence_if_new(conn, word_id, de, en, career=None):
    """Insert a sentence unless an identical German sentence already exists for
    this word (case-insensitive). Returns the new sentence id, or None if it was
    blank or a duplicate. `career` tags the sentence to a career (None = generic)."""
    de, en = de.strip(), en.strip()
    if not de or not en:
        return None
    dup = conn.execute(
        "SELECT 1 FROM sentences WHERE word_id = ? AND LOWER(sentence_de) = LOWER(?)",
        (word_id, de),
    ).fetchone()
    if dup:
        return None
    cur = conn.execute(
        "INSERT INTO sentences (word_id, sentence_de, sentence_en, career) VALUES (?, ?, ?, ?)",
        (word_id, de, en, (career or None)),
    )
    return cur.lastrowid


def find_word(conn, word):
    """Return the id of an existing word matching case-insensitively, or None."""
    row = conn.execute(
        "SELECT id FROM words WHERE LOWER(word) = LOWER(?)", (word.strip(),)
    ).fetchone()
    return row["id"] if row else None


def add_word(word, topic="general", sentences=None, level="B1",
             lemma=None, pos=None, article=None, audio_url=None, word_url=None,
             image_url=None, unit_id=None):
    """Add a word, or merge sentences into an existing word with the same text
    (case-insensitive). Duplicate sentences are skipped. `level` is the CEFR level
    the word is taught at; lemma/pos/article are extra dictionary metadata,
    audio_url is the pronunciation .mp3 link, word_url links to the word's
    dictionary page, and image_url is a link to an image of the word.
    On an existing word these fields are updated to the values provided.
    Returns (word_id, created) where `created` is True only if a new word row was inserted."""
    level = (level or "B1").strip().upper() or "B1"
    cat = (topic or "general").strip() or "general"
    meta = tuple((v or "").strip() or None for v in (lemma, pos, article, audio_url, word_url, image_url))
    with connect() as conn:
        existing = find_word(conn, word)
        if existing is not None:
            word_id, created = existing, False
            conn.execute(
                "UPDATE words SET level=?, topic=?, lemma=?, pos=?, article=?, audio_url=?, word_url=?, image_url=?, unit_id=? WHERE id=?",
                (level, cat, *meta, unit_id, word_id))
        else:
            cur = conn.execute(
                "INSERT INTO words (word, topic, level, lemma, pos, article, audio_url, word_url, image_url, unit_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (word.strip(), cat, level, *meta, unit_id))
            word_id, created = cur.lastrowid, True
        for de, en in (sentences or []):
            _insert_sentence_if_new(conn, word_id, de, en)
        return word_id, created


def add_sentence(word_id, sentence_de, sentence_en):
    """Add a sentence to a word, skipping exact (case-insensitive) duplicates.
    Returns the new id, 0 if it was a duplicate, or None if the word is missing."""
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM words WHERE id = ?", (word_id,)).fetchone():
            return None
        sid = _insert_sentence_if_new(conn, word_id, sentence_de, sentence_en)
        return sid if sid is not None else 0


def get_meanings(word_id):
    """Return list of meaning strings for a word, ordered by position."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT meaning FROM word_meanings WHERE word_id = ? ORDER BY position",
            (word_id,),
        ).fetchall()
        return [r["meaning"] for r in rows]


def set_meanings(word_id, meanings: list[str]):
    """Replace all meanings for a word."""
    with connect() as conn:
        conn.execute("DELETE FROM word_meanings WHERE word_id = ?", (word_id,))
        for i, m in enumerate(meanings):
            m = m.strip()
            if m:
                conn.execute(
                    "INSERT INTO word_meanings (word_id, meaning, position) VALUES (?, ?, ?)",
                    (word_id, m, i),
                )


def get_tags(word_id):
    """Return list of tag strings for a word, alphabetically sorted."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT tag FROM word_tags WHERE word_id = ? ORDER BY tag",
            (word_id,),
        ).fetchall()
        return [r["tag"] for r in rows]


def set_tags(word_id, tags: list[str]):
    """Replace all tags for a word."""
    with connect() as conn:
        conn.execute("DELETE FROM word_tags WHERE word_id = ?", (word_id,))
        for t in tags:
            t = t.strip().lower()
            if t:
                conn.execute(
                    "INSERT OR IGNORE INTO word_tags (word_id, tag) VALUES (?, ?)",
                    (word_id, t),
                )


def set_sentence_tags(sentence_id, tags: list[str]):
    """Replace all tags for a sentence."""
    with connect() as conn:
        conn.execute("DELETE FROM sentence_tags WHERE sentence_id = ?", (sentence_id,))
        for t in tags:
            t = t.strip().lower()
            if t:
                conn.execute(
                    "INSERT OR IGNORE INTO sentence_tags (sentence_id, tag) VALUES (?, ?)",
                    (sentence_id, t),
                )


def get_sentence_tags(sentence_id):
    """Get all tags for a sentence."""
    with connect() as conn:
        rows = conn.execute("SELECT tag FROM sentence_tags WHERE sentence_id = ? ORDER BY tag", (sentence_id,)).fetchall()
        return [r["tag"] for r in rows]


def delete_word(word_id):
    with connect() as conn:
        cur = conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
        return cur.rowcount > 0


def delete_sentence(sentence_id):
    with connect() as conn:
        cur = conn.execute("DELETE FROM sentences WHERE id = ?", (sentence_id,))
        return cur.rowcount > 0


def _sentence_dict(s):
    return {
        "id": s["id"], "sentence_de": s["sentence_de"],
        "sentence_en": s["sentence_en"], "career": s["career"],
    }


def list_words(career=None, user_id=None):
    """All words, each with its sentences (newest word first).

    When `career` is given, each word's `sentences` are the ones tagged for that
    career plus generic (untagged) sentences; `has_career_sentences` flags whether
    any career-specific sentence already exists. When `career` is None, every
    sentence is returned (admin/browse view). When `user_id` is also given, each
    word gets a `paid` flag (whether this user was already charged for it under
    this career) so the client can avoid re-requesting already-paid words."""
    with connect() as conn:
        words = conn.execute("SELECT * FROM words ORDER BY id DESC").fetchall()
        sents = conn.execute("SELECT * FROM sentences ORDER BY id ASC").fetchall()
        meanings_rows = conn.execute(
            "SELECT word_id, meaning FROM word_meanings ORDER BY word_id, position"
        ).fetchall()
        tags_rows = conn.execute(
            "SELECT word_id, tag FROM word_tags ORDER BY word_id, tag"
        ).fetchall()
        paid_ids = set()
        if user_id is not None and career is not None:
            paid_ids = {r["word_id"] for r in conn.execute(
                "SELECT word_id FROM token_charges WHERE user_id = ? AND career = ?",
                (user_id, career),
            ).fetchall()}
    by_word = {}
    has_career = {}
    for s in sents:
        c = s["career"]
        if career is None or c is None or c == career:
            by_word.setdefault(s["word_id"], []).append(_sentence_dict(s))
        if career is not None and c == career:
            has_career[s["word_id"]] = True
    meanings_by_word = {}
    for m in meanings_rows:
        meanings_by_word.setdefault(m["word_id"], []).append(m["meaning"])
    tags_by_word = {}
    for t in tags_rows:
        tags_by_word.setdefault(t["word_id"], []).append(t["tag"])
    out = []
    for w in words:
        d = dict(w)
        d["sentences"] = by_word.get(w["id"], [])
        d["meanings"] = meanings_by_word.get(w["id"], [])
        d["tags"] = tags_by_word.get(w["id"], [])
        # Include approved, active ads that match this word's tags
        d["ads"] = get_ads_for_word(w["id"])
        if career is not None:
            d["has_career_sentences"] = has_career.get(w["id"], False)
            if user_id is not None:
                d["paid"] = w["id"] in paid_ids
        out.append(d)
    return out


def career_sentence_count(word_id, career):
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM sentences WHERE word_id = ? AND career = ?",
            (word_id, career),
        ).fetchone()
        return row["c"]


def add_career_sentences(word_id, career, pairs):
    """Store AI-generated (de, en) pairs tagged with a career. Returns the list of
    inserted sentence dicts (skipping duplicates)."""
    inserted = []
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM words WHERE id = ?", (word_id,)).fetchone():
            return []
        for de, en in pairs:
            sid = _insert_sentence_if_new(conn, word_id, de, en, career=career)
            if sid:
                inserted.append({"id": sid, "sentence_de": de.strip(),
                                 "sentence_en": en.strip(), "career": career})
    return inserted


def add_career_sentences_with_tags(word_id, career, sentences_with_tags):
    """Store sentences with their tags. Expects list of dicts:
    [{"de": "...", "en": "...", "tags": [...]}, ...]
    Returns list of inserted sentence dicts."""
    inserted = []
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM words WHERE id = ?", (word_id,)).fetchone():
            return []
        for item in sentences_with_tags:
            de = item.get("de")
            en = item.get("en")
            tags = item.get("tags", [])
            if de and en:
                sid = _insert_sentence_if_new(conn, word_id, de, en, career=career)
                if sid:
                    # Store tags for this sentence
                    for tag in tags:
                        tag = tag.strip().lower()
                        if tag:
                            conn.execute(
                                "INSERT OR IGNORE INTO sentence_tags (sentence_id, tag) VALUES (?, ?)",
                                (sid, tag),
                            )
                    inserted.append({"id": sid, "sentence_de": de.strip(),
                                     "sentence_en": en.strip(), "career": career, "tags": tags})
    return inserted


def categories():
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT topic FROM words ORDER BY topic"
        ).fetchall()
        return [r["topic"] for r in rows]


def career_suggestions(limit=200):
    """Distinct careers that users have entered (most-used first) — used to seed
    the career combo box so the list grows as people fill in their own."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT career, COUNT(*) AS n FROM profiles
               WHERE career IS NOT NULL AND TRIM(career) != ''
               GROUP BY LOWER(TRIM(career)) ORDER BY n DESC, career ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [r["career"] for r in rows]


# --------------------------------------------------------------------------
# per-user progress
# --------------------------------------------------------------------------
def get_progress(user_id):
    """Return {word_id: {reps, interval, ease, lapses, due}} for a user."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM progress WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {
        r["word_id"]: {
            "reps": r["reps"], "interval": r["interval"], "ease": r["ease"],
            "lapses": r["lapses"], "due": r["due"],
        }
        for r in rows
    }


def upsert_progress(user_id, word_id, reps, interval, ease, lapses, due):
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM words WHERE id = ?", (word_id,)).fetchone():
            return False
        conn.execute(
            """INSERT INTO progress (user_id, word_id, reps, interval, ease, lapses, due, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(user_id, word_id) DO UPDATE SET
                   reps=excluded.reps, interval=excluded.interval, ease=excluded.ease,
                   lapses=excluded.lapses, due=excluded.due, updated_at=datetime('now')""",
            (user_id, word_id, reps, interval, round(ease, 4), lapses, due),
        )
        return True


# --------------------------------------------------------------------------
# learner profile (career / level / daily goal) + lesson learning state
# --------------------------------------------------------------------------
def get_profile(user_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT career, level, location, daily_goal FROM profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def save_profile(user_id, career, level, daily_goal, location=None):
    with connect() as conn:
        conn.execute(
            """INSERT INTO profiles (user_id, career, level, location, daily_goal, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                   career=excluded.career, level=excluded.level, location=excluded.location,
                   daily_goal=excluded.daily_goal, updated_at=datetime('now')""",
            (user_id, career, level, location, int(daily_goal)),
        )
        return True


def get_learning(user_id):
    """Return {"learned": [word_id, ...], "wrong": {word_id: count}}."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT word_id, learned, wrong FROM learning WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {
        "learned": [r["word_id"] for r in rows if r["learned"]],
        "wrong": {r["word_id"]: r["wrong"] for r in rows if r["wrong"]},
    }


def save_learning(user_id, learned, wrong):
    """Replace the user's full learning state. `learned` is a list of word ids;
    `wrong` is a {word_id: count} mapping."""
    learned = {int(w) for w in learned}
    wrong = {int(k): int(v) for k, v in (wrong or {}).items()}
    ids = learned | set(wrong)
    with connect() as conn:
        valid = {r["id"] for r in conn.execute("SELECT id FROM words").fetchall()}
        conn.execute("DELETE FROM learning WHERE user_id = ?", (user_id,))
        for wid in ids:
            if wid not in valid:
                continue
            conn.execute(
                "INSERT INTO learning (user_id, word_id, learned, wrong) VALUES (?, ?, ?, ?)",
                (user_id, wid, 1 if wid in learned else 0, wrong.get(wid, 0)),
            )
        return True


# --------------------------------------------------------------------------
# private per-user notes on words
# --------------------------------------------------------------------------
def get_notes(user_id):
    """Return {word_id: note} for a user."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT word_id, note FROM notes WHERE user_id = ?", (user_id,)
        ).fetchall()
    return {r["word_id"]: r["note"] for r in rows}


def save_note(user_id, word_id, note):
    """Upsert (or delete, if blank) a user's private note for a word."""
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM words WHERE id = ?", (word_id,)).fetchone():
            return False
        if (note or "").strip() == "":
            conn.execute("DELETE FROM notes WHERE user_id = ? AND word_id = ?", (user_id, word_id))
            return True
        conn.execute(
            """INSERT INTO notes (user_id, word_id, note, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(user_id, word_id) DO UPDATE SET
                   note=excluded.note, updated_at=datetime('now')""",
            (user_id, word_id, note.strip()),
        )
        return True


# --------------------------------------------------------------------------
# grammar topics (shared, read-focused)
# --------------------------------------------------------------------------
def slugify(title):
    t = title.strip().lower()
    for k, v in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.items():
        t = t.replace(k, v)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "topic"


def list_grammar():
    """Sidebar list: titles only (no body), ordered by position then title."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, slug, topic, position FROM grammar "
            "ORDER BY position ASC, title ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_grammar(slug):
    with connect() as conn:
        row = conn.execute("SELECT * FROM grammar WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None


def add_grammar(title, body, topic="general", position=0):
    """Create or update (by slug) a grammar topic. Returns its id."""
    slug = slugify(title)
    with connect() as conn:
        conn.execute(
            """INSERT INTO grammar (title, slug, topic, body, position, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(slug) DO UPDATE SET
                   title=excluded.title, topic=excluded.topic,
                   body=excluded.body, position=excluded.position,
                   updated_at=datetime('now')""",
            (title.strip(), slug, (topic or "general").strip() or "general",
             body, position),
        )
        return conn.execute("SELECT id FROM grammar WHERE slug = ?", (slug,)).fetchone()["id"]


def delete_grammar(grammar_id):
    with connect() as conn:
        cur = conn.execute("DELETE FROM grammar WHERE id = ?", (grammar_id,))
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# readings (admin-posted stories, unlocked as the user progresses)
# --------------------------------------------------------------------------
def list_readings():
    """All readings ordered by position then id; titles + level, no body."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, level, position FROM readings ORDER BY position ASC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_reading(reading_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
        return dict(row) if row else None


def add_reading(title, body, level="B1", position=0, reading_id=None, audio_url=None):
    """Create a reading, or update an existing one when reading_id is given.
    Returns the reading id."""
    lvl = (level or "B1").strip().upper() or "B1"
    audio = (audio_url or "").strip() or None
    with connect() as conn:
        if reading_id:
            conn.execute(
                """UPDATE readings SET title=?, body=?, level=?, position=?, audio_url=?,
                       updated_at=datetime('now') WHERE id=?""",
                (title.strip(), body, lvl, int(position), audio, reading_id),
            )
            return reading_id
        cur = conn.execute(
            """INSERT INTO readings (title, body, level, position, audio_url)
               VALUES (?, ?, ?, ?, ?)""",
            (title.strip(), body, lvl, int(position), audio),
        )
        return cur.lastrowid


def set_reading_audio(reading_id, audio_url):
    with connect() as conn:
        cur = conn.execute(
            "UPDATE readings SET audio_url=?, updated_at=datetime('now') WHERE id=?",
            (audio_url, reading_id),
        )
        return cur.rowcount > 0


def delete_reading(reading_id):
    with connect() as conn:
        cur = conn.execute("DELETE FROM readings WHERE id = ?", (reading_id,))
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# units (admin-built packs of words, unlocked by spending tokens)
# --------------------------------------------------------------------------
def _unit_word_map(conn):
    """unit_id -> [word_id,...] (ordered by word id)."""
    m = {}
    for r in conn.execute("SELECT id, unit_id FROM words WHERE unit_id IS NOT NULL ORDER BY id ASC").fetchall():
        m.setdefault(r["unit_id"], []).append(r["id"])
    return m


def list_units(level=None, user_id=None):
    """Units ordered by (level, position, id). Each carries its word ids; with a
    user_id, also a `paid` flag (has the user unlocked it)."""
    print(f"🔍 [DEBUG] list_units() called - Reading from database only (NO external endpoint calls)")
    with connect() as conn:
        sql = "SELECT * FROM units"
        args = ()
        if level:
            sql += " WHERE level = ?"
            args = (level,)
        sql += " ORDER BY level ASC, position ASC, id ASC"
        rows = conn.execute(sql, args).fetchall()
        wmap = _unit_word_map(conn)
        paid = set()
        if user_id is not None:
            paid = {r["unit_id"] for r in conn.execute(
                "SELECT unit_id FROM unit_unlocks WHERE user_id = ?", (user_id,)).fetchall()}
        scored = set()
        if user_id is not None:
            scored = {r["unit_id"] for r in conn.execute(
                "SELECT unit_id FROM unit_scores WHERE user_id = ?", (user_id,)).fetchall()}
        out = []
        for r in rows:
            d = dict(r)
            d["word_ids"] = wmap.get(r["id"], [])
            if user_id is not None:
                # First unit is always unlocked (so user can start), OR user has unlocked it
                d["paid"] = (r["position"] == 1) or (r["id"] in paid)
                d["score_earned"] = r["id"] in scored
            out.append(d)
        print(f"✅ [DEBUG] list_units() completed - Read {len(out)} units from database only (NO external endpoint calls)")
        return out


def get_unit(unit_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["word_ids"] = [r["id"] for r in conn.execute(
            "SELECT id FROM words WHERE unit_id = ? ORDER BY id ASC", (unit_id,)).fetchall()]
        return d


def save_unit(title, level, token_cost=0, position=0, unit_id=None, **kwargs):
    lvl = (level or "B1").strip().upper() or "B1"
    with connect() as conn:
        if unit_id:
            conn.execute(
                """UPDATE units SET title=?, level=?, token_cost=?, position=?, quiz_score=?,
                       updated_at=datetime('now') WHERE id=?""",
                (title.strip(), lvl, max(0, int(token_cost)), int(position),
                 max(0, int(kwargs.get("quiz_score", 6))), unit_id))
            return unit_id
        cur = conn.execute(
            "INSERT INTO units (title, level, token_cost, position, quiz_score) VALUES (?, ?, ?, ?, ?)",
            (title.strip(), lvl, max(0, int(token_cost)), int(position),
             max(0, int(kwargs.get("quiz_score", 6)))))
        return cur.lastrowid


def auto_assign_units(unit_size=None):
    """Group all words (ordered by id) into units of `unit_size` words each.
    Words already in a valid unit are left alone. Unassigned words fill the
    last existing auto-unit first, then new units are created as needed.
    unit_size defaults to the UNIT_SIZE env var, then 10."""
    if unit_size is None:
        try:
            unit_size = int(os.getenv("UNIT_SIZE", "10"))
        except (ValueError, TypeError):
            unit_size = 10
    unit_size = max(1, unit_size)

    with connect() as conn:
        # All words ordered oldest-first (stable order so unit membership is stable)
        all_words = conn.execute(
            "SELECT id FROM words ORDER BY id ASC"
        ).fetchall()
        if not all_words:
            return

        word_ids = [r["id"] for r in all_words]
        total = len(word_ids)

        # Existing auto-units ordered by position
        existing = conn.execute(
            "SELECT id, position FROM units ORDER BY position ASC, id ASC"
        ).fetchall()

        # Compute how many units we need
        import math
        needed = math.ceil(total / unit_size)

        # Create missing units
        unit_ids = [r["id"] for r in existing]
        next_pos = (existing[-1]["position"] + 1) if existing else 1
        while len(unit_ids) < needed:
            n = len(unit_ids) + 1
            cur = conn.execute(
                "INSERT INTO units (title, level, token_cost, position, quiz_score) VALUES (?, ?, ?, ?, ?)",
                (f"Unit {n}", "B1", 0, next_pos, 6),
            )
            unit_ids.append(cur.lastrowid)
            next_pos += 1

        # Assign words to units in order
        for i, wid in enumerate(word_ids):
            uid = unit_ids[i // unit_size]
            conn.execute("UPDATE words SET unit_id = ? WHERE id = ?", (uid, wid))


def delete_unit(unit_id):
    with connect() as conn:
        conn.execute("UPDATE words SET unit_id = NULL WHERE unit_id = ?", (unit_id,))
        cur = conn.execute("DELETE FROM units WHERE id = ?", (unit_id,))
        return cur.rowcount > 0


def award_unit_score(user_id, unit_id):
    """Award the unit's quiz_score to the user (once only). Returns score awarded (0 if already claimed)."""
    with connect() as conn:
        unit = conn.execute("SELECT quiz_score FROM units WHERE id = ?", (unit_id,)).fetchone()
        if not unit:
            return 0
        score = unit["quiz_score"] or 0
        cur = conn.execute(
            "INSERT OR IGNORE INTO unit_scores (user_id, unit_id, score) VALUES (?, ?, ?)",
            (user_id, unit_id, score))
        return score if cur.rowcount else 0


def award_call_score(user_id, score, call_log_id=None):
    """Award score stars to a user for answering a call."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO call_scores (user_id, score, call_log_id) VALUES (?, ?, ?)",
            (user_id, score, call_log_id),
        )


def get_user_score(user_id):
    """Total score earned by the user across all units + call rewards."""
    with connect() as conn:
        quiz_row = conn.execute(
            "SELECT COALESCE(SUM(score), 0) AS total FROM unit_scores WHERE user_id = ?",
            (user_id,)).fetchone()
        call_row = conn.execute(
            "SELECT COALESCE(SUM(score), 0) AS total FROM call_scores WHERE user_id = ?",
            (user_id,)).fetchone()
        earned = {r["unit_id"]: r["score"] for r in conn.execute(
            "SELECT unit_id, score FROM unit_scores WHERE user_id = ?", (user_id,)).fetchall()}
        total = (quiz_row["total"] or 0) + (call_row["total"] or 0)
        return {"total": total, "by_unit": earned}


# --------------------------------------------------------------------------
# inbox
# --------------------------------------------------------------------------

def send_message(user_id, subject, body, icon="📬"):
    """Deliver a message to a user's inbox."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO inbox (user_id, subject, body, icon) VALUES (?, ?, ?, ?)",
            (user_id, subject, body, icon),
        )


def get_inbox(user_id):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM inbox WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def unread_count(user_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM inbox WHERE user_id = ? AND read = 0",
            (user_id,),
        ).fetchone()
        return row["n"]


def mark_read(user_id, message_id=None):
    """Mark one message (or all) as read."""
    with connect() as conn:
        if message_id is not None:
            conn.execute(
                "UPDATE inbox SET read = 1 WHERE id = ? AND user_id = ?",
                (message_id, user_id),
            )
        else:
            conn.execute(
                "UPDATE inbox SET read = 1 WHERE user_id = ?",
                (user_id,),
            )


# --------------------------------------------------------------------------
# call-ready / peer calls
# --------------------------------------------------------------------------

CALL_COST_DEFAULT = 10


def call_cost():
    v = get_setting("call_cost")
    try:
        return int(v) if v else CALL_COST_DEFAULT
    except (ValueError, TypeError):
        return CALL_COST_DEFAULT


def set_call_ready(user_id, ready: bool):
    """Enable/disable call-ready. Free toggle — no token requirement."""
    with connect() as conn:
        conn.execute(
            "UPDATE users SET call_ready = ? WHERE id = ?",
            (1 if ready else 0, user_id),
        )
        return True, None


def initiate_call(caller_id, callee_id):
    """Caller pays call_cost() tokens. Callee earns call_cost() score stars. Returns (ok, callee_name|reason)."""
    cost = call_cost()
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, tokens, call_ready, name FROM users WHERE id IN (?, ?)",
            (caller_id, callee_id),
        ).fetchall()
        by_id = {r["id"]: r for r in rows}
        caller = by_id.get(caller_id)
        callee = by_id.get(callee_id)
        if not caller or not callee:
            return False, "user_not_found"
        if not callee["call_ready"]:
            return False, "callee_not_ready"
        if caller["tokens"] < cost:
            return False, "caller_insufficient"
        # Only caller pays tokens
        conn.execute("UPDATE users SET tokens = tokens - ? WHERE id = ?", (cost, caller_id))
        # Log the call
        cur = conn.execute(
            "INSERT INTO call_logs (caller_id, callee_id, tokens_each) VALUES (?, ?, ?)",
            (caller_id, callee_id, cost),
        )
        call_log_id = cur.lastrowid
        # Callee earns score stars equal to call cost
        conn.execute(
            "INSERT INTO call_scores (user_id, score, call_log_id) VALUES (?, ?, ?)",
            (callee_id, cost, call_log_id),
        )
        return True, callee["name"]


def set_unit_words(unit_id, word_ids):
    """Make exactly `word_ids` the members of this unit (clears others)."""
    ids = [int(w) for w in word_ids]
    with connect() as conn:
        conn.execute("UPDATE words SET unit_id = NULL WHERE unit_id = ?", (unit_id,))
        for wid in ids:
            conn.execute("UPDATE words SET unit_id = ? WHERE id = ?", (unit_id, wid))
        return True


def _unit_completed(conn, user_id, word_ids):
    if not word_ids:
        return True
    qs = ",".join("?" * len(word_ids))
    n = conn.execute(
        f"SELECT COUNT(*) c FROM learning WHERE user_id=? AND learned=1 AND word_id IN ({qs})",
        (user_id, *word_ids)).fetchone()["c"]
    return n >= len(word_ids)


def unlock_unit(user_id, unit_id):
    """Spend the unit's tokens to unlock it for the user. Enforces: not already
    unlocked, previous unit completed, enough tokens. Returns
    {ok, tokens, reason}."""
    with connect() as conn:
        unit = conn.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()
        if not unit:
            return {"ok": False, "reason": "not_found"}
        if conn.execute("SELECT 1 FROM unit_unlocks WHERE user_id=? AND unit_id=?",
                        (user_id, unit_id)).fetchone():
            row = conn.execute("SELECT tokens FROM users WHERE id=?", (user_id,)).fetchone()
            return {"ok": True, "tokens": row["tokens"], "already": True}
        # previous unit (same level) must be completed
        prev = conn.execute(
            """SELECT * FROM units WHERE level=? AND (position < ? OR (position=? AND id < ?))
               ORDER BY position DESC, id DESC LIMIT 1""",
            (unit["level"], unit["position"], unit["position"], unit_id)).fetchone()
        if prev:
            prev_words = [r["id"] for r in conn.execute(
                "SELECT id FROM words WHERE unit_id=?", (prev["id"],)).fetchall()]
            if not _unit_completed(conn, user_id, prev_words):
                return {"ok": False, "reason": "prev_incomplete"}
        cost = int(unit["token_cost"])
        cur = conn.execute(
            "UPDATE users SET tokens = tokens - ? WHERE id=? AND tokens >= ?",
            (cost, user_id, cost))
        if cur.rowcount == 0:
            return {"ok": False, "reason": "insufficient"}
        conn.execute("INSERT INTO unit_unlocks (user_id, unit_id, tokens) VALUES (?, ?, ?)",
                     (user_id, unit_id, cost))
        bal = conn.execute("SELECT tokens FROM users WHERE id=?", (user_id,)).fetchone()["tokens"]
        return {"ok": True, "tokens": bal, "spent": cost}


def unlock_unit_for_user(user_id, unit_id):
    """Mark a unit as unlocked for a user (used when completing a unit). No token cost."""
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO unit_unlocks (user_id, unit_id, tokens) VALUES (?, ?, ?)",
            (user_id, unit_id, 0))
        return True


# --------------------------------------------------------------------------
# token packages (admin-defined) + purchases
# --------------------------------------------------------------------------
def list_packages(active_only=False):
    sql = "SELECT * FROM token_packages"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY position ASC, price_cents ASC"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_package(pkg_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM token_packages WHERE id = ?", (pkg_id,)).fetchone()
        return dict(row) if row else None


def save_package(tokens, price_cents, currency="EUR", active=True, position=0, pkg_id=None):
    with connect() as conn:
        if pkg_id:
            conn.execute(
                """UPDATE token_packages SET tokens=?, price_cents=?, currency=?,
                       active=?, position=? WHERE id=?""",
                (int(tokens), int(price_cents), currency, 1 if active else 0, int(position), pkg_id),
            )
            return pkg_id
        cur = conn.execute(
            """INSERT INTO token_packages (tokens, price_cents, currency, active, position)
               VALUES (?, ?, ?, ?, ?)""",
            (int(tokens), int(price_cents), currency, 1 if active else 0, int(position)),
        )
        return cur.lastrowid


def delete_package(pkg_id):
    with connect() as conn:
        cur = conn.execute("DELETE FROM token_packages WHERE id = ?", (pkg_id,))
        return cur.rowcount > 0


def record_purchase(user_id, package_id, tokens, price_cents, currency, provider, provider_ref):
    """Record a completed purchase and credit the tokens. Idempotent on provider_ref
    (a repeated capture callback won't double-credit). Returns the new balance or None
    if this purchase was already recorded."""
    with connect() as conn:
        if provider_ref and conn.execute(
            "SELECT 1 FROM purchases WHERE provider_ref = ?", (provider_ref,)
        ).fetchone():
            return None  # already processed
        conn.execute(
            """INSERT INTO purchases (user_id, package_id, tokens, price_cents, currency, provider, provider_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, package_id, int(tokens), int(price_cents), currency, provider, provider_ref),
        )
        conn.execute("UPDATE users SET tokens = tokens + ? WHERE id = ?", (int(tokens), user_id))
        row = conn.execute("SELECT tokens FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["tokens"] if row else None


# --------------------------------------------------------------------------
# api logging + admin dashboard
# --------------------------------------------------------------------------
def log_event(action, status, detail=None, user_id=None, word_id=None, career=None):
    """Append a row to api_log. Never raises (logging must not break the request)."""
    try:
        with connect() as conn:
            conn.execute(
                """INSERT INTO api_log (user_id, action, status, detail, word_id, career)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, action, status, (detail or "")[:500], word_id, career),
            )
    except Exception:
        pass


def log_access(user_id, event, ip=None, user_agent=None, language=None, referer=None, path=None):
    """Record request header info for a session event. Never raises."""
    try:
        with connect() as conn:
            conn.execute(
                """INSERT INTO access_log (user_id, event, ip, user_agent, language, referer, path)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, event, ip, (user_agent or "")[:400], (language or "")[:200],
                 (referer or "")[:300], path),
            )
    except Exception:
        pass


def admin_dashboard(recent=40):
    """Everything the admin dashboard needs in one payload."""
    with connect() as conn:
        def scalar(sql, args=()):
            r = conn.execute(sql, args).fetchone()
            return list(r)[0] if r else 0

        users = [dict(r) for r in conn.execute(
            """SELECT u.id, u.email, u.name, u.picture, u.tokens, u.created_at,
                      p.career, p.level, p.daily_goal,
                      (SELECT COUNT(*) FROM learning l WHERE l.user_id = u.id AND l.learned = 1) AS learned,
                      (SELECT COUNT(*) FROM learning l WHERE l.user_id = u.id AND l.wrong > 0) AS mistakes,
                      (SELECT COUNT(*) FROM token_charges t WHERE t.user_id = u.id) AS charges
               FROM users u LEFT JOIN profiles p ON p.user_id = u.id
               ORDER BY u.created_at DESC"""
        ).fetchall()]

        # distinct careers across all users (with how many users have each)
        careers = [dict(r) for r in conn.execute(
            """SELECT career, COUNT(*) AS users FROM profiles
               WHERE career IS NOT NULL AND TRIM(career) != ''
               GROUP BY career ORDER BY users DESC, career ASC"""
        ).fetchall()]

        # per-user units (completed batches) and readings unlocked
        UNITS_PER_READING = 2
        total_readings = scalar("SELECT COUNT(*) FROM readings")
        words_by_level = {}
        for w in conn.execute("SELECT id, level FROM words ORDER BY id ASC").fetchall():
            words_by_level.setdefault(w["level"] or "B1", []).append(w["id"])
        learned_by_user = {}
        for r in conn.execute("SELECT user_id, word_id FROM learning WHERE learned = 1").fetchall():
            learned_by_user.setdefault(r["user_id"], set()).add(r["word_id"])
        for u in users:
            deck = words_by_level.get(u["level"] or "B1", [])
            goal = u["daily_goal"] or 10
            learned = learned_by_user.get(u["id"], set())
            passed = total_units = 0
            for i in range(0, len(deck), goal):
                chunk = deck[i:i + goal]
                total_units += 1
                if chunk and all(wid in learned for wid in chunk):
                    passed += 1
            u["units_passed"] = passed
            u["total_units"] = total_units
            u["readings_unlocked"] = min(passed // UNITS_PER_READING, total_readings)
            u["total_readings"] = total_readings

        by_status = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM api_log WHERE action='generate' GROUP BY status"
        ).fetchall()}

        recent_logs = [dict(r) for r in conn.execute(
            """SELECT a.created_at, a.action, a.status, a.detail, a.word_id, a.career,
                      u.email, w.word
               FROM api_log a LEFT JOIN users u ON u.id = a.user_id
                              LEFT JOIN words w ON w.id = a.word_id
               ORDER BY a.id DESC LIMIT ?""", (recent,)
        ).fetchall()]

        error_logs = [dict(r) for r in conn.execute(
            """SELECT a.created_at, a.action, a.status, a.detail, a.career, u.email
               FROM api_log a LEFT JOIN users u ON u.id = a.user_id
               WHERE a.status = 'error' ORDER BY a.id DESC LIMIT ?""", (recent,)
        ).fetchall()]

        access_logs = [dict(r) for r in conn.execute(
            """SELECT a.created_at, a.event, a.ip, a.user_agent, a.language, a.referer, u.email
               FROM access_log a LEFT JOIN users u ON u.id = a.user_id
               ORDER BY a.id DESC LIMIT ?""", (recent,)
        ).fetchall()]
        # latest access per user (SQLite returns the row matching MAX(created_at))
        last_access = {r["user_id"]: dict(r) for r in conn.execute(
            "SELECT user_id, ip, MAX(created_at) AS last_seen FROM access_log GROUP BY user_id"
        ).fetchall()}
        for u in users:
            la = last_access.get(u["id"])
            u["last_seen"] = la["last_seen"] if la else None
            u["last_ip"] = la["ip"] if la else None

        packages = list_packages()
        recent_purchases = [dict(r) for r in conn.execute(
            """SELECT p.created_at, p.tokens, p.price_cents, p.currency, p.provider, p.provider_ref, u.email
               FROM purchases p LEFT JOIN users u ON u.id = p.user_id
               ORDER BY p.id DESC LIMIT ?""", (recent,)
        ).fetchall()]

        summary = {
            "users": scalar("SELECT COUNT(*) FROM users"),
            "tokens_remaining": scalar("SELECT COALESCE(SUM(tokens),0) FROM users"),
            "tokens_spent": scalar("SELECT COUNT(*) FROM token_charges"),
            "generations": by_status.get("generated", 0),
            "cached_hits": by_status.get("cached", 0),
            "errors": by_status.get("error", 0),
            "words": scalar("SELECT COUNT(*) FROM words"),
            "sentences": scalar("SELECT COUNT(*) FROM sentences"),
            "ai_sentences": scalar("SELECT COUNT(*) FROM sentences WHERE career IS NOT NULL"),
            "readings": scalar("SELECT COUNT(*) FROM readings"),
            "purchases": scalar("SELECT COUNT(*) FROM purchases"),
            "revenue_cents": scalar("SELECT COALESCE(SUM(price_cents),0) FROM purchases"),
            "referrals": scalar("SELECT COUNT(*) FROM referrals"),
            "referral_tokens_awarded": scalar("SELECT COALESCE(SUM(tokens),0) FROM referrals"),
        }
    return {"summary": summary, "users": users, "careers": careers,
            "packages": packages, "recent_purchases": recent_purchases,
            "access_logs": access_logs,
            "recent_logs": recent_logs, "error_logs": error_logs}


# --------------------------------------------------------------------------
# companies & advertisements
# --------------------------------------------------------------------------
def create_company(email, password, name, contact_name=None, contact_phone=None):
    """Create a company account. Raises ValueError if email is taken.
    Returns the new company row."""
    email = email.strip().lower()
    if get_company_by_email(email):
        raise ValueError("email already registered")
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO companies (email, password_hash, name, contact_name, contact_phone, approved) VALUES (?, ?, ?, ?, ?, ?)",
                (email, hash_password(password), name, contact_name, contact_phone, 0),
            )
        except sqlite3.IntegrityError:
            raise ValueError("email already registered")
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


def get_company(company_id):
    """Get company by ID."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        return dict(row) if row else None


def get_company_by_email(email):
    """Get company by email."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM companies WHERE LOWER(email) = ?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else None


def authenticate_company(email, password):
    """Return the company row if email+password match, else None."""
    company = get_company_by_email(email)
    if company and company.get("password_hash") and verify_password(password, company["password_hash"]):
        return company
    return None


def list_companies(approved=None):
    """List companies. If approved is not None, filter by approval status."""
    with connect() as conn:
        if approved is None:
            rows = conn.execute("SELECT * FROM companies ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM companies WHERE approved = ? ORDER BY created_at DESC", (1 if approved else 0,)).fetchall()
        return [dict(r) for r in rows]


def approve_company(company_id, approved=True):
    """Set company approval status."""
    with connect() as conn:
        conn.execute("UPDATE companies SET approved = ? WHERE id = ?", (1 if approved else 0, company_id))


def create_advertisement(company_id, title, description, tags, image_url=None, image_type=None):
    """Create an ad for a company. Tags is a list of strings.
    Returns the new advertisement row."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO advertisements (company_id, title, description, image_url, image_type) VALUES (?, ?, ?, ?, ?)",
            (company_id, title, description, image_url, image_type),
        )
        ad_id = cur.lastrowid
        for tag in tags:
            conn.execute("INSERT OR IGNORE INTO ad_tags (ad_id, tag) VALUES (?, ?)", (ad_id, tag.lower()))
        row = conn.execute("SELECT * FROM advertisements WHERE id = ?", (ad_id,)).fetchone()
        return dict(row)


def get_advertisement(ad_id):
    """Get ad by ID with tags."""
    with connect() as conn:
        ad = conn.execute("SELECT * FROM advertisements WHERE id = ?", (ad_id,)).fetchone()
        if not ad:
            return None
        ad = dict(ad)
        tags = conn.execute("SELECT tag FROM ad_tags WHERE ad_id = ? ORDER BY tag", (ad_id,)).fetchall()
        ad["tags"] = [t["tag"] for t in tags]
        return ad


def list_company_ads(company_id, approved=None):
    """List ads for a company. If approved is not None, filter by approval status."""
    with connect() as conn:
        if approved is None:
            rows = conn.execute("SELECT * FROM advertisements WHERE company_id = ? ORDER BY created_at DESC", (company_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM advertisements WHERE company_id = ? AND approved = ? ORDER BY created_at DESC", (company_id, 1 if approved else 0)).fetchall()
        ads = []
        for row in rows:
            ad = dict(row)
            tags = conn.execute("SELECT tag FROM ad_tags WHERE ad_id = ? ORDER BY tag", (ad["id"],)).fetchall()
            ad["tags"] = [t["tag"] for t in tags]
            ads.append(ad)
        return ads


def list_pending_advertisements(approved=False):
    """List all pending ads (not approved) or approved ads, for admin dashboard."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT a.*, c.name as company_name FROM advertisements a JOIN companies c ON c.id = a.company_id WHERE a.approved = ? ORDER BY a.created_at DESC",
            (1 if approved else 0,)
        ).fetchall()
        ads = []
        for row in rows:
            ad = dict(row)
            tags = conn.execute("SELECT tag FROM ad_tags WHERE ad_id = ? ORDER BY tag", (ad["id"],)).fetchall()
            ad["tags"] = [t["tag"] for t in tags]
            ads.append(ad)
        return ads


def approve_advertisement(ad_id, approved=True):
    """Set ad approval status."""
    with connect() as conn:
        conn.execute("UPDATE advertisements SET approved = ? WHERE id = ?", (1 if approved else 0, ad_id))


def update_advertisement(ad_id, title=None, description=None, tags=None, image_url=None, image_type=None, active=None):
    """Update ad metadata."""
    with connect() as conn:
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if image_url is not None:
            updates.append("image_url = ?")
            params.append(image_url)
        if image_type is not None:
            updates.append("image_type = ?")
            params.append(image_type)
        if active is not None:
            updates.append("active = ?")
            params.append(1 if active else 0)
        if updates:
            updates.append("updated_at = datetime('now')")
            params.append(ad_id)
            conn.execute(f"UPDATE advertisements SET {', '.join(updates)} WHERE id = ?", params)
        if tags is not None:
            conn.execute("DELETE FROM ad_tags WHERE ad_id = ?", (ad_id,))
            for tag in tags:
                conn.execute("INSERT OR IGNORE INTO ad_tags (ad_id, tag) VALUES (?, ?)", (ad_id, tag.lower()))


def delete_advertisement(ad_id):
    """Delete an ad."""
    with connect() as conn:
        conn.execute("DELETE FROM advertisements WHERE id = ?", (ad_id,))


def get_ads_for_word(word_id):
    """Get all approved, active ads that match the word's tags OR sentence tags."""
    with connect() as conn:
        # Get word-level tags
        word_tags = conn.execute("SELECT tag FROM word_tags WHERE word_id = ?", (word_id,)).fetchall()
        word_tag_list = [t["tag"].lower() for t in word_tags]

        # Get tags from all sentences for this word
        sentence_tags = conn.execute(
            """SELECT DISTINCT st.tag FROM sentence_tags st
               JOIN sentences s ON st.sentence_id = s.id
               WHERE s.word_id = ?""",
            (word_id,)
        ).fetchall()
        sentence_tag_list = [t["tag"].lower() for t in sentence_tags]

        # Combine all tags
        all_tags = list(set(word_tag_list + sentence_tag_list))

        if not all_tags:
            return []

        placeholders = ",".join("?" * len(all_tags))
        rows = conn.execute(
            f"""SELECT DISTINCT a.* FROM advertisements a
               WHERE a.approved = 1 AND a.active = 1
               AND a.id IN (SELECT DISTINCT ad_id FROM ad_tags WHERE tag IN ({placeholders}))
               ORDER BY a.created_at DESC""",
            all_tags
        ).fetchall()
        ads = []
        for row in rows:
            ad = dict(row)
            tags = conn.execute("SELECT tag FROM ad_tags WHERE ad_id = ?", (ad["id"],)).fetchall()
            ad["tags"] = [t["tag"] for t in tags]
            ads.append(ad)
        return ads


def get_words_for_ad(ad_id):
    """Get all words whose tags match this ad's tags."""
    with connect() as conn:
        # Get ad tags
        ad_tags = conn.execute("SELECT tag FROM ad_tags WHERE ad_id = ?", (ad_id,)).fetchall()
        ad_tag_list = [t["tag"].lower() for t in ad_tags]

        if not ad_tag_list:
            return []

        # Find all words that have matching tags
        placeholders = ",".join("?" * len(ad_tag_list))
        rows = conn.execute(
            f"""SELECT DISTINCT w.id, w.word FROM words w
               WHERE w.id IN (
                   SELECT DISTINCT word_id FROM word_tags WHERE tag IN ({placeholders})
               )
               ORDER BY w.word""",
            ad_tag_list
        ).fetchall()

        return [dict(r) for r in rows]


def count_words_for_ad(ad_id):
    """Count how many words match this ad's tags."""
    return len(get_words_for_ad(ad_id))


def get_all_tags():
    """Get all unique tags from word_tags table."""
    with connect() as conn:
        rows = conn.execute("SELECT DISTINCT tag FROM word_tags ORDER BY tag").fetchall()
        return [r["tag"] for r in rows]


# --------------------------------------------------------------------------
# Readings
# --------------------------------------------------------------------------
def get_reading_by_unit(unit_id):
    """Get the saved reading for a unit, if it exists."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, title, body, level FROM readings WHERE unit_id = ?",
            (unit_id,)
        ).fetchone()
        return dict(row) if row else None


def save_reading(title, body, level, unit_id):
    """Save a generated reading to the database."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO readings (title, body, level, unit_id) VALUES (?, ?, ?, ?)",
            (title, body, level, unit_id)
        )
        conn.commit()  # Explicitly commit the transaction
        # Get the ID of the inserted row
        reading_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return reading_id


# --------------------------------------------------------------------------
# API tokens
# --------------------------------------------------------------------------
def create_api_token(user_id, name=None):
    """Generate a new API token for a user."""
    import secrets
    token = secrets.token_urlsafe(32)
    with connect() as conn:
        conn.execute(
            "INSERT INTO api_tokens (user_id, token, name) VALUES (?, ?, ?)",
            (user_id, token, name)
        )
    return token


def get_user_by_token(token):
    """Validate token and return user if valid."""
    with connect() as conn:
        row = conn.execute(
            "SELECT u.* FROM users u JOIN api_tokens t ON u.id = t.user_id WHERE t.token = ?",
            (token,)
        ).fetchone()
        if row:
            # Update last_used_at
            conn.execute("UPDATE api_tokens SET last_used_at = datetime('now') WHERE token = ?", (token,))
            return dict(row)
        return None


def list_api_tokens(user_id):
    """List all API tokens for a user."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, last_used_at FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def revoke_api_token(user_id, token_id):
    """Revoke an API token."""
    with connect() as conn:
        conn.execute(
            "DELETE FROM api_tokens WHERE id = ? AND user_id = ?",
            (token_id, user_id)
        )
