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
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS words (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        word        TEXT NOT NULL,
        category    TEXT NOT NULL DEFAULT 'general',
        level       TEXT NOT NULL DEFAULT 'B1',
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
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
        category    TEXT NOT NULL DEFAULT 'general',
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
    scols = [r["name"] for r in conn.execute("PRAGMA table_info(sentences)").fetchall()]
    if scols and "career" not in scols:
        conn.execute("ALTER TABLE sentences ADD COLUMN career TEXT")
    wcols = [r["name"] for r in conn.execute("PRAGMA table_info(words)").fetchall()]
    if wcols and "level" not in wcols:
        conn.execute("ALTER TABLE words ADD COLUMN level TEXT NOT NULL DEFAULT 'B1'")
    rcols = [r["name"] for r in conn.execute("PRAGMA table_info(readings)").fetchall()]
    if rcols and "audio_url" not in rcols:
        conn.execute("ALTER TABLE readings ADD COLUMN audio_url TEXT")


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
    """Create or update a user by their Google subject id. Returns the row."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO users (sub, email, name, picture, tokens) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(sub) DO UPDATE SET email=excluded.email,
                   name=excluded.name, picture=excluded.picture""",
            (sub, email, name, picture, START_TOKENS),
        )
        row = conn.execute("SELECT * FROM users WHERE sub = ?", (sub,)).fetchone()
        return dict(row)


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


def add_word(word, category="general", sentences=None, level="B1"):
    """Add a word, or merge sentences into an existing word with the same text
    (case-insensitive). Duplicate sentences are skipped. `level` is the CEFR level
    the word is taught at (used to scope a learner's deck); on an existing word the
    level is updated to the value provided.
    Returns (word_id, created) where `created` is True only if a new word row
    was inserted."""
    level = (level or "B1").strip().upper() or "B1"
    with connect() as conn:
        existing = find_word(conn, word)
        if existing is not None:
            word_id, created = existing, False
            conn.execute("UPDATE words SET level = ? WHERE id = ?", (level, word_id))
        else:
            cur = conn.execute(
                "INSERT INTO words (word, category, level) VALUES (?, ?, ?)",
                (word.strip(), (category or "general").strip() or "general", level),
            )
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
    out = []
    for w in words:
        d = dict(w)
        d["sentences"] = by_word.get(w["id"], [])
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


def categories():
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM words ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]


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
            "SELECT career, level, daily_goal FROM profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def save_profile(user_id, career, level, daily_goal):
    with connect() as conn:
        conn.execute(
            """INSERT INTO profiles (user_id, career, level, daily_goal, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                   career=excluded.career, level=excluded.level,
                   daily_goal=excluded.daily_goal, updated_at=datetime('now')""",
            (user_id, career, level, int(daily_goal)),
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
            "SELECT id, title, slug, category, position FROM grammar "
            "ORDER BY position ASC, title ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_grammar(slug):
    with connect() as conn:
        row = conn.execute("SELECT * FROM grammar WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None


def add_grammar(title, body, category="general", position=0):
    """Create or update (by slug) a grammar topic. Returns its id."""
    slug = slugify(title)
    with connect() as conn:
        conn.execute(
            """INSERT INTO grammar (title, slug, category, body, position, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(slug) DO UPDATE SET
                   title=excluded.title, category=excluded.category,
                   body=excluded.body, position=excluded.position,
                   updated_at=datetime('now')""",
            (title.strip(), slug, (category or "general").strip() or "general",
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
        }
    return {"summary": summary, "users": users, "careers": careers,
            "packages": packages, "recent_purchases": recent_purchases,
            "access_logs": access_logs,
            "recent_logs": recent_logs, "error_logs": error_logs}
