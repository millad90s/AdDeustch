# FlashCard App — Full Feature Specification
> Use this document to rebuild the app from scratch. It covers every feature, data model, API endpoint, and UI behaviour implemented so far.

---

## 1. Tech Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python) |
| Database | SQLite (single file `flashcards.db`) |
| Auth | Google OAuth 2.0 via `authlib` + optional local email/password |
| AI | Google Gemini (`gemini-2.5-flash`) or Anthropic Claude (switchable via `AI_PROVIDER` env var) |
| Payments | PayPal REST API (create-order + capture-order, no webhooks) |
| Frontend | Next.js 14+ App Router, TypeScript, Tailwind CSS, shadcn/ui |
| Real-time | SSE (Server-Sent Events) for push notifications + WebSocket for WebRTC signaling |
| Video calls | WebRTC peer-to-peer (STUN only for same-network, add TURN for production) |

---

## 2. Environment Variables (`.env`)

```
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
OAUTH_REDIRECT_URI=https://yourdomain.com/auth/callback

SESSION_SECRET=<random 64 hex chars>
ADMIN_EMAILS=you@example.com

AI_PROVIDER=gemini                  # or "claude"
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
ANTHROPIC_API_KEY=                  # only if AI_PROVIDER=claude
ANTHROPIC_MODEL=claude-opus-4-8

START_TOKENS=5                      # tokens given to new users
TOKEN_COST_GENERATE=1               # tokens spent per AI sentence generation

PAYPAL_ENV=live                     # or "sandbox"
PAYPAL_CLIENT_ID=
PAYPAL_SECRET=
```

> All `os.getenv()` calls must be **lazy** (inside functions, not at module level) so they run after `load_dotenv()`.

---

## 3. Database Schema

All schema changes must be **additive migrations** inside a single `_migrate(conn)` function — never drop or recreate tables.

### Tables

#### `users`
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| sub | TEXT UNIQUE | Google OAuth subject, null for local users |
| email | TEXT UNIQUE | |
| name | TEXT | |
| picture | TEXT | Google profile photo URL |
| password_hash | TEXT | bcrypt, null for Google users |
| ref_code | TEXT UNIQUE | referral code (auto-generated) |
| referred_by | INTEGER FK | user_id who referred them |
| tokens | INTEGER | default = START_TOKENS env var |
| call_ready | INTEGER | 0 or 1, default 0 |
| career | TEXT | selected career/field |
| level | TEXT | language level (A1–C2) |
| daily_goal | INTEGER | words per day |
| created_at | REAL | unix timestamp |

#### `words`
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| word | TEXT UNIQUE | German word |
| translation | TEXT | English translation |
| category | TEXT | general / devops / etc |
| level | TEXT | A1–C2 |
| audio_url | TEXT | TTS audio URL |

#### `sentences`
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| word_id | INTEGER FK | |
| sentence_de | TEXT | German example sentence |
| sentence_en | TEXT | English translation |
| career | TEXT | career context (nullable) |

#### `progress`
| column | type | notes |
|---|---|---|
| user_id | INTEGER FK | |
| word_id | INTEGER FK | |
| reps | INTEGER | spaced repetition count |
| interval | INTEGER | days until next review |
| ease | REAL | ease factor |
| lapses | INTEGER | number of failures |
| due | REAL | unix timestamp of next due date |
| PRIMARY KEY | (user_id, word_id) | |

#### `units`
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| title | TEXT | |
| description | TEXT | |
| level | TEXT | A1–C2 |
| token_cost | INTEGER | tokens required to unlock |
| quiz_score | INTEGER | score awarded on passing quiz |
| position | INTEGER | display order |

#### `unit_words`
| column | type | notes |
|---|---|---|
| unit_id | INTEGER FK | |
| word_id | INTEGER FK | |
| PRIMARY KEY | (unit_id, word_id) | |

#### `user_units`
| column | type | notes |
|---|---|---|
| user_id | INTEGER FK | |
| unit_id | INTEGER FK | |
| un_at | REAL | unix timestamp |
| completed_at | REAL | nullable |
| PRIMARY KEY | (user_id, unit_id) | |

#### `unit_scores`
| column | type | notes |
|---|---|---|
| user_id | INTEGER FK | |
| unit_id | INTEGER FK | |
| score | INTEGER | |
| awarded_at | REAL | unix timestamp |
| PRIMARY KEY | (user_id, unit_id) | idempotent — INSERT OR IGNORE |

#### `inbox`
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER FK | recipient |
| icon | TEXT | emoji icon |
| subject | TEXT | |
| body | TEXT | can contain `room_id:<hex>` for call messages |
| read | INTEGER | 0 or 1, default 0 |
| created_at | REAL | unix timestamp |

#### `call_logs`
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| caller_id | INTEGER FK | |
| callee_id | INTEGER FK | |
| tokens_each | INTEGER | tokens deducted per side |
| created_at | REAL | unix timestamp |

#### `packages`
Token purchase packages (admin-configured):

| column | type |
|---|---|
| id | INTEGER PK |
| tokens | INTEGER |
| price_cents | INTEGER |
| currency | TEXT |
| active | INTEGER |
| position | INTEGER |

#### `purchases`
| column | type |
|---|---|
| id | INTEGER PK |
| user_id | INTEGER FK |
| package_id | INTEGER FK |
| tokens | INTEGER |
| price_cents | INTEGER |
| currency | TEXT |
| provider | TEXT |
| provider_ref | TEXT UNIQUE |
| created_at | REAL |

#### `grammar`
| column | type |
|---|---|
| id | INTEGER PK |
| title | TEXT |
| slug | TEXT UNIQUE |
| body | TEXT (markdown) |
| category | TEXT |
| position | INTEGER |

#### `readings`
Short reading passages with optional audio:

| column | type |
|---|---|
| id | INTEGER PK |
| title | TEXT |
| body | TEXT |
| level | TEXT |
| position | INTEGER |
| audio_url | TEXT |

#### `settings`
Key-value store for app-wide settings:

| column | type |
|---|---|
| key | TEXT PK |
| value | TEXT |

Configurable settings: `start_tokens`, `token_cost_generate`, `call_cost`, `referral_tokens`, `referral_bonus`.

#### `event_log`
| column | type |
|---|---|
| id | INTEGER PK |
| action | TEXT |
| status | TEXT |
| detail | TEXT |
| user_id | INTEGER |
| word_id | INTEGER |
| career | TEXT |
| created_at | REAL |

#### `access_log`
| column | type |
|---|---|
| id | INTEGER PK |
| user_id | INTEGER |
| event | TEXT |
| ip | TEXT |
| user_agent | TEXT |
| language | TEXT |
| referer | TEXT |
| path | TEXT |
| created_at | REAL |

---

## 4. API Endpoints

### Auth
| Method | Path | Description |
|---|---|---|
| POST | `/auth/signup` | Local email/password registration. Body: `{email, password, name, ref?}`. Awards START_TOKENS. Triggers referral reward if ref code valid. |
| POST | `/auth/login` | Local login. Body: `{email, password}`. Returns user session. |
| POST | `/auth/logout` | Clear session. |
| GET | `/auth/google` | Redirect to Google OAuth consent screen. |
| GET | `/auth/callback` | Google OAuth callback. Creates or updates user. |

### Me & Session
| Method | Path | Description |
|---|---|---|
| GET | `/api/me` | Returns `{google_enabled, ai_enabled, paypal_enabled, paypal_client_id, user}`. `user` is null if not logged in. |
| GET | `/api/events` | SSE stream. Pushes `{type, ...}` events. `type: "incoming_call"` includes `caller_name` and `room_id`. Heartbeat every 20s. |

### Words
| Method | Path | Description |
|---|---|---|
| GET | `/api/words` | List all words. Optional `?career=` filter. Returns words with sentences. |
| POST | `/api/words` | Admin: add a word. |
| POST | `/api/words/batch` | Admin: add multiple words at once. |
| DELETE | `/api/words/{id}` | Admin: delete word and its sentences. |
| POST | `/api/words/{id}/generate` | Spend 1 token → generate AI example sentences for a word in user's career context. Body: `{career}`. |
| POST | `/api/words/{id}/sentences` | Admin: manually add a sentence. |
| DELETE | `/api/sentences/{id}` | Admin: delete a sentence. |

### Progress (Spaced Repetition)
| Method | Path | Description |
|---|---|---|
| GET | `/api/progress` | Get user's spaced-repetition state for all words. |
| PUT | `/api/progress/{word_id}` | Update word progress. Body: `{reps, interval, ease, lapses, due}`. |

### Units (Lessons)
| Method | Path | Description |
|---|---|---|
| GET | `/api/units` | List all units with /completed state for current user. |
| POST | `/api/units` | Admin: create a unit. Body: `{title, description, level, token_cost, quiz_score, position}`. |
| PUT | `/api/units/{id}/words` | Admin: set words for a unit. Body: `{word_ids: []}`. |
| DELETE | `/api/units/{id}` | Admin: delete unit. |
| POST | `/api/units/{id}/unlock` | User spends `token_cost` tokens to unlock a unit. |
| POST | `/api/units/{id}/score` | Award quiz score to user after passing quiz. Idempotent. Sends inbox message. |

### Score & Leaderboard
| Method | Path | Description |
|---|---|---|
| GET | `/api/score` | Returns `{total, by_unit: {unit_id: score}}`. |
| GET | `/api/leaderboard` | Returns `{entries: [...], call_cost}`. Each entry: `{id, name, picture, tokens, score, call_ready, me}`. |

### Inbox
| Method | Path | Description |
|---|---|---|
| GET | `/api/inbox` | List all messages for current user, newest first. |
| GET | `/api/inbox/unread` | Returns `{count}`. |
| POST | `/api/inbox/read-all` | Mark all messages as read. |
| POST | `/api/inbox/{id}/read` | Mark one message as read. |

### Calls
| Method | Path | Description |
|---|---|---|
| POST | `/api/call/ready` | Toggle call availability. Body: `{ready: bool}`. Requires `tokens >= call_cost` to enable. |
| GET | `/api/call/cost` | Returns `{cost}` in tokens. |
| POST | `/api/call/initiate` | Deduct `call_cost` tokens from both caller and callee. Create a signaling room. Send inbox message to callee with `room_id` embedded. Push SSE `incoming_call` event to callee. Returns `{room_id, tokens, callee_name}`. |
| GET | `/api/call/room/{room_id}` | Check if room is valid and user is a participant. Returns `{valid: bool}`. |
| WS | `/ws/call/{room_id}` | WebSocket signaling relay. Max 2 peers. Sends `{type: "role", role: "caller"|"callee"}` on connect. Relays offer/answer/ice-candidate/bye messages between peers. |

### Profile & Learning
| Method | Path | Description |
|---|---|---|
| GET | `/api/profile` | Get user profile (career, level, daily_goal). |
| PUT | `/api/profile` | Update profile. Body: `{career, level, daily_goal}`. |
| GET | `/api/learning` | Get learning stats (learned count, wrong count). |
| PUT | `/api/learning` | Update learning stats. |

### Referrals
| Method | Path | Description |
|---|---|---|
| GET | `/api/referral` | Get current user's referral code and stats (invited count, tokens earned). |
| GET | `/api/ref/{code}` | Get info about a referral code (referrer name). |
| POST | `/api/ref` | Stash a referral code in session before signup. |

### Payments (PayPal)
| Method | Path | Description |
|---|---|---|
| GET | `/api/packages` | List active token packages. |
| POST | `/api/paypal/create-order` | Create a PayPal order. Body: `{package_id}`. Returns `{order_id}`. |
| POST | `/api/paypal/capture-order` | Capture approved order. Body: `{order_id}`. Adds tokens to user. Returns `{ok, tokens}`. |

### Grammar
| Method | Path | Description |
|---|---|---|
| GET | `/api/grammar` | List all grammar articles. |
| GET | `/api/grammar/{slug}` | Get a single grammar article. |
| POST | `/api/grammar` | Admin: create article. Body: `{title, body, category, position}`. |
| DELETE | `/api/grammar/{id}` | Admin: delete article. |

### Readings
| Method | Path | Description |
|---|---|---|
| GET | `/api/readings` | List all reading passages. |
| GET | `/api/readings/{id}` | Get one reading passage. |
| POST | `/api/readings` | Admin: create reading. Body: `{title, body, level, position}`. |
| POST | `/api/readings/{id}/audio` | Admin: upload audio file for a reading. |
| DELETE | `/api/readings/{id}` | Admin: delete reading. |

### Admin
| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/dashboard` | Admin stats: user count, word count, sentence count, recent events, recent access. |
| GET | `/api/admin/settings` | Get all configurable settings. |
| POST | `/api/admin/settings` | Update settings: `start_tokens`, `token_cost_generate`, `call_cost`, `referral_tokens`, `referral_bonus`. |
| POST | `/api/admin/grant-tokens` | Grant tokens to a user by email. |

---

## 5. Core Feature Behaviours

### Token Economy
- New users receive `START_TOKENS` (configurable, default 5) on registration.
- Tokens are spent to: unlock units, generate AI sentences, initiate calls.
- Tokens are earned by: referrals bringing new users.
- Tokens are purchased via PayPal.
- Token balance shown in topbar as `🪙 N`.

### Referral System
- Every user has a unique referral code.
- Share link: `/register?ref=<code>`
- When a referred user signs up: referrer earns `referral_tokens` tokens, new user earns `referral_bonus` tokens.
- Both parties receive an inbox message.
- Referral stats available on profile page.

### Spaced Repetition (SM-2 algorithm)
- Implemented entirely client-side in the browser.
- Progress (reps, interval, ease, lapses, due date) is synced to the server via `PUT /api/progress/{word_id}`.
- Words are shown in a flashcard format: German on front, English + example sentence on back.
- User rates recall: Again / Hard / Good / Easy.
- 10 words per lesson (fixed).

### Units & Quiz
- Units are groups of words with a title, level, token cost to unlock, and a score value.
- Once un, the user can take a 10-question multiple-choice quiz.
- Quiz has Back/Forward navigation — answers are preserved while navigating.
- On passing, `POST /api/units/{id}/score` is called once (idempotent — INSERT OR IGNORE in DB).
- Score is added to user's total and shown in the progress section.
- Each unit card shows: title, cost to unlock (🪙), score value (⭐), /un/completed state.

### Inbox
- Server-side message system. Messages are stored in `inbox` table.
- Messages sent automatically for: referral rewards, quiz score awards, incoming calls.
- Messages can contain `room_id:<hex>` which the frontend parses to show a "Join call 📞" button.
- Unread count shown as red badge on bell icon in topbar.
- Inbox opens as a slide-in sheet on the right side.
- "Mark all read" button available.

### Real-time Notifications (SSE)
- Each logged-in browser holds an open `GET /api/events` connection.
- Server pushes events as JSON: `data: {"type": "incoming_call", "caller_name": "...", "room_id": "..."}\n\n`
- Heartbeat comment (`: heartbeat\n\n`) sent every 20s to keep connection alive.
- Client reconnects automatically after 3s on error.
- On `incoming_call` event: play ringtone + show ring banner.

### Ring Tone
- Generated programmatically via Web Audio API — no audio file needed.
- A shared `AudioContext` is created on first user interaction (click/keydown) to satisfy browser autoplay policy.
- Before each ring cycle, `ctx.resume()` is called in case the browser suspended it.
- Pattern: two 0.4s beeps (480Hz + 420Hz) separated by 0.1s, repeated every 2s.
- Stops on Accept or Decline.

### Video/Audio Calls
- Caller clicks "Call" in leaderboard → `POST /api/call/initiate` → tokens deducted from both → room created → SSE push to callee.
- Callee sees ring banner → clicks Accept → joins the room.
- Both open WebSocket to `/ws/call/{room_id}`.
- Signaling flow:
  1. Server assigns roles: first joiner = "caller", second = "callee".
  2. Callee sends `{type: "ready"}`.
  3. Caller creates and sends SDP offer.
  4. Callee answers.
  5. ICE candidates exchanged.
  6. `RTCPeerConnection` established — video/audio streams.
- Controls: mute mic, toggle camera, hang up.
- Full-screen call modal with remote video large, local video small (picture-in-picture bottom-right).
- Call room expires after 30 minutes (in-memory, purged on next request).
- Only works peer-to-peer on same network with STUN. For cross-network production use, add TURN server credentials (e.g. Metered.ca).

### AI Sentence Generation
- User spends 1 token to generate career-specific example sentences for a word.
- AI prompt includes the German word, its translation, and the user's selected career.
- Returns 3 sentence pairs (German + English).
- Sentences are stored in the DB and deduplication-safe (INSERT OR IGNORE on content hash).
- Cached in DB — same word+career combo won't regenerate if sentences already exist.

### Career Filtering
- Users select their career/field during onboarding.
- Words and AI sentences are filtered/generated based on career.
- Career stored in user profile.
- Career selector is a `<select>` dropdown with an "Other" option that reveals a free-text input.

### Google Profile Images
- All `<img>` tags showing Google profile photos must have `referrerPolicy="no-referrer"` to prevent `lh3.googleusercontent.com` from blocking them.

### Admin Panel
- Accessible only to users whose email is in `ADMIN_EMAILS` env var.
- Features: view dashboard stats, manage settings, add/delete words, add sentences, manage units, manage grammar, manage readings, grant tokens to users.

### Grammar Section
- Markdown articles with title, category, and position.
- Rendered as formatted articles in the frontend.

### Readings Section
- Short reading passages with title, body, level, and optional audio upload.
- Audio served from `/media/` path.
- Un progressively (every N completed units).

---

## 6. Frontend Pages & Components

### Pages
| Route | Description |
|---|---|
| `/` | Root: redirect to `/dashboard` if logged in, else `/login` |
| `/login` | Google OAuth button + guest mode |
| `/dashboard` | Units grid with lock/unlock/complete states + stats row |
| `/leaderboard` | Ranked user list + call-ready toggle + Call buttons |
| `/progress` | Per-unit score breakdown + overall progress bar |
| `/profile` | Avatar, referral link, buy tokens, sign out |

### Global Components (on every page)
- **Topbar**: sticky, shows app logo, `🪙 N` token chip, `⭐ N` score chip, inbox bell with unread badge, user avatar.
- **BottomNav**: mobile-only fixed bottom bar with Learn / Leaders / Progress / Profile tabs.
- **InboxSheet**: slide-in drawer from right showing all inbox messages. Messages with `room_id` show "Join call 📞" button.
- **CallModal**: fullscreen call UI. Hidden until a call starts. Managed globally so it persists across page navigations.
- **RingBanner**: fixed top-center banner that appears on incoming call. Shows caller name, Accept and Decline buttons. Auto-dismisses after 40s.

### Responsive Design
- Mobile-first with Tailwind CSS responsive prefixes (`sm:`, `md:`, `lg:`).
- Bottom navigation on mobile (`md:hidden`).
- Sidebar navigation on desktop (hidden on mobile).
- All cards and grids use responsive column counts.

---

## 7. Next.js Proxy Config

`next.config.ts` rewrites so Next.js (port 3000) proxies to FastAPI (port 8000):

```ts
async rewrites() {
  return [
    { source: "/api/:path*",  destination: "http://localhost:8000/api/:path*" },
    { source: "/auth/:path*", destination: "http://localhost:8000/auth/:path*" },
    { source: "/ws/:path*",   destination: "http://localhost:8000/ws/:path*" },
  ];
}
```

---

## 8. Key Implementation Notes

1. **PayPal**: All `os.getenv()` calls must be inside functions (lazy), not at module level — otherwise they run before `load_dotenv()`.
2. **SSE**: Use `asyncio.Queue` per connected user. Store in a dict `{user_id: Queue}`. Clean up on disconnect.
3. **WebSocket rooms**: Store in memory `{room_id: {caller_id, callee_id, expires_at}}`. Purge expired on each request.
4. **Unit scores**: Use `INSERT OR IGNORE` with `PRIMARY KEY (user_id, unit_id)` — idempotent, never double-award.
5. **AudioContext**: Create once on first user gesture, reuse for all ring tones. Call `resume()` before each use.
6. **Referral flow**: Stash ref code in session on landing → apply on signup (not on login).
7. **`suppressHydrationWarning`**: Add to `<html>` tag in Next.js layout to suppress errors from browser extensions modifying the DOM.
8. **Google images**: Always use `referrerPolicy="no-referrer"` on profile photo `<img>` tags.
9. **DB migrations**: Never drop tables. All schema changes go in `_migrate(conn)` as `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` or `CREATE TABLE IF NOT EXISTS`.
10. **Call cost**: Both caller AND callee spend tokens. Check callee has enough tokens before initiating. If callee is not call-ready, reject with `callee_not_ready`.
