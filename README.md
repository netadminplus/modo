# 🤖 Telegram Group Management Bot

A high-performance, multi-group Telegram Management Bot with a Web Dashboard, specializing in **Forum Topic ACL management** and granular user permissions.

Built with **Aiogram 3.x** (async), **FastAPI**, **PostgreSQL**, **Redis**, and **Docker**.

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Network                           │
│                                                                 │
│  ┌──────────┐    ┌─────────────────────────────────────────┐   │
│  │  Nginx   │───▶│          App Container                  │   │
│  │ (Proxy + │    │  ┌─────────────┐  ┌──────────────────┐  │   │
│  │   SSL)   │    │  │  Aiogram Bot│  │  FastAPI Web UI  │  │   │
│  └──────────┘    │  │  (polling / │  │  (Dashboard +    │  │   │
│       │          │  │   webhook)  │  │   REST API)      │  │   │
│       │          │  └──────┬──────┘  └────────┬─────────┘  │   │
│  ┌────▼─────┐   │          │                  │            │   │
│  │ Certbot  │   │          └──────────┬────────┘            │   │
│  │  (SSL)   │   │                     │                     │   │
│  └──────────┘   └─────────────────────┼─────────────────────┘   │
│                               ┌───────▼──────┐                  │
│                         ┌─────┤  Core Layer  ├─────┐            │
│                         │     └──────────────┘     │            │
│                    ┌────▼──────┐            ┌───────▼──────┐    │
│                    │ PostgreSQL│            │    Redis     │    │
│                    │(Relational│            │(Cache/State/ │    │
│                    │   Data)   │            │ Rate-limit)  │    │
│                    └───────────┘            └──────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
my_bot_project/
├── bot/                          # Aiogram bot logic
│   ├── handlers/
│   │   ├── group_setup.py        # Bot join/leave events
│   │   ├── topic_acl.py          # ★ Topic ACL guard + commands
│   │   ├── moderation.py         # Anti-flood, warn, ban, mute, kick
│   │   └── welcome.py            # Greetings, captcha, service msgs
│   ├── middlewares/
│   │   └── db_middleware.py      # DB session + mod settings injection
│   ├── filters/
│   │   └── admin_filter.py       # IsGroupAdmin, IsBotAdmin, IsOwner
│   ├── keyboards/                # Reusable InlineKeyboard builders
│   ├── utils/
│   │   └── helpers.py            # format_template, send_and_delete, etc.
│   └── main.py                   # Dispatcher setup + bot entry point
│
├── web/                          # FastAPI dashboard
│   ├── app.py                    # Routes + auth + API endpoints
│   ├── health.py                 # /health check endpoint
│   ├── lifespan.py               # Startup/shutdown hooks
│   ├── templates/
│   │   ├── auth/login.html       # Telegram Login Widget page
│   │   ├── dashboard/
│   │   │   ├── home.html         # Group list
│   │   │   ├── group_settings.html # Per-group settings + toggles
│   │   │   └── topics.html       # Topic ACL management
│   │   └── partials/sidebar.html
│   └── static/                   # CSS, JS, images
│
├── core/                         # Shared business logic
│   ├── config.py                 # Pydantic Settings loader
│   ├── models/
│   │   └── database.py           # SQLAlchemy ORM models
│   ├── services/
│   │   ├── group_service.py      # DB operations (groups, ACL, templates)
│   │   └── cache_service.py      # Redis operations
│   └── utils/
│       └── admin_sync.py         # Telegram admin list → DB sync
│
├── migrations/                   # Alembic migrations
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py       # Initial schema
│
├── nginx/
│   ├── nginx.conf                # Main Nginx config
│   └── conf.d/app.conf           # Virtual host + SSL config
│
├── data/                         # Persistent volumes (git-ignored)
│   ├── pg_data/                  # PostgreSQL data
│   ├── redis_data/               # Redis AOF data
│   ├── certbot/                  # Let's Encrypt certs
│   └── logs/                     # App + Nginx logs
│
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── requirements.txt
├── alembic.ini
└── .env                          # ← Fill this in before starting
```

---

## 🚀 Quick Start

### 1. Clone and Configure

```bash
git clone <your-repo> my_bot_project
cd my_bot_project
cp .env .env.example   # Keep a backup
```

Edit `.env` with your values:

```ini
BOT_TOKEN=123456789:AAF...          # From @BotFather
BOT_USERNAME=your_bot_username       # Without @
ADMIN_IDS=123456789                  # Your Telegram user ID
POSTGRES_PASSWORD=change_this        # Strong password
REDIS_PASSWORD=change_this_too
SECRET_KEY=random_64_char_string     # python -c "import secrets; print(secrets.token_hex(32))"
DOMAIN=yourdomain.com
CERTBOT_EMAIL=admin@yourdomain.com
```

### 2. DNS Setup

Point your domain's A record to your server's IP:
```
A  yourdomain.com  →  YOUR_SERVER_IP
```

### 3. Get SSL Certificate (first time only)

```bash
# Start Nginx in HTTP-only mode first for ACME challenge
docker compose up -d nginx
docker compose run --rm certbot
docker compose restart nginx
```

### 4. Launch Everything

```bash
docker compose up -d
docker compose logs -f app
```

That's it! Your bot and dashboard are live. 🎉

---

## ⚙️ Core Features

### 🔒 Topic ACL (Forum Mode)

The most powerful feature. For Telegram groups with **Forum Mode** enabled:

| Command | Description |
|---------|-------------|
| `/restrict_topic` | Lock the current topic (must be used inside the topic) |
| `/unrestrict_topic` | Open the topic to everyone |
| `/allow_user <id>` | Whitelist a user in the current topic |
| `/deny_user <id>` | Remove a user from the whitelist |
| `/topic_users` | List all whitelisted users |

**How it works:**
1. Every message in a forum topic is checked.
2. If the topic is restricted → check if sender is admin or whitelisted.
3. If not → message is **instantly deleted** + self-deleting warning sent.
4. All checks use **Redis caching** (5 min TTL) for near-zero DB load.

### 🛡️ Moderation Suite

| Feature | Description |
|---------|-------------|
| **Anti-flood** | Rate-limit per user/group with configurable threshold, window, and action (mute/kick/ban) |
| **Anti-link** | Auto-delete messages containing URLs from non-admins |
| **Word filter** | Configurable comma-separated banned words list |
| **Warn system** | `/warn`, `/warnings`, `/resetwarns` with auto-action on max warnings |
| **Captcha** | Math captcha for new members; restricts until solved |
| **Welcome/Farewell** | Customizable greeting + optional self-deleting farewell |
| **Service msg cleaner** | Auto-delete Telegram join/left service messages |

### 📝 Message Templates

Every bot response is fully customizable via the Web Dashboard or `/settings`. Available variables:

| Variable | Description |
|----------|-------------|
| `{user_mention}` | HTML mention of the user |
| `{user_name}` | Plain display name |
| `{group_title}` | Group name |
| `{count}` | Current warning count |
| `{max}` | Maximum warnings |
| `{reason}` | Warning/action reason |
| `{duration}` | Mute duration string |
| `{a}`, `{b}` | Captcha math operands |

---

## 🌐 Web Dashboard

Access at `https://yourdomain.com`

### Authentication
Uses the **Telegram Login Widget** — no separate password needed. Users authenticate with their Telegram account. Only group admins (synced from Telegram) can access their group's settings.

### Pages

| Page | URL | Description |
|------|-----|-------------|
| Login | `/login` | Telegram Login Widget |
| Dashboard | `/dashboard` | List of administered groups |
| Group Settings | `/dashboard/group/{id}` | All settings for one group |
| Topic ACL | `/dashboard/group/{id}/topics` | Manage restricted topics |

### REST API

All settings changes go through the REST API (used by the dashboard JS):

```
POST   /api/group/{id}/settings                    Update moderation toggles
POST   /api/group/{id}/template/{key}              Update a message template
POST   /api/group/{id}/topic/{tid}/restrict        Restrict a topic
DELETE /api/group/{id}/topic/{tid}/restrict        Unrestrict a topic
POST   /api/group/{id}/topic/{tid}/user/{uid}      Whitelist a user
DELETE /api/group/{id}/topic/{tid}/user/{uid}      Remove from whitelist
GET    /api/group/{id}/logs                        Activity log (JSON)
GET    /health                                     Service health check
```

---

## 🗄️ Database Schema

```
groups                  — Registered Telegram groups
telegram_users          — Cached user profiles
group_admins            — Admin list per group (synced from API)
topic_acls              — ★ Topic restriction + whitelist entries
moderation_settings     — Per-group feature toggles
message_templates       — Editable message templates
user_warnings           — Warning counters
activity_logs           — Audit trail of all moderation actions
captcha_pending         — Pending captcha verifications
```

### Running Migrations

```bash
# Apply all migrations
docker compose exec app alembic upgrade head

# Generate a new migration after model changes
docker compose exec app alembic revision --autogenerate -m "add_new_feature"

# Roll back one step
docker compose exec app alembic downgrade -1
```

---

## 🔧 Bot Permissions Required

Make the bot an **admin** with these permissions:

- ✅ Delete messages
- ✅ Ban users
- ✅ Restrict members
- ✅ Manage topics (for Forum mode)
- ✅ Pin messages (optional)

---

## 🛠️ Development

### Run locally without Docker

```bash
# Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL and Redis (via Docker)
docker compose up -d postgres redis

# Run DB migrations
alembic upgrade head

# Start the bot (polling mode)
python -m bot.main polling &

# Start the web dashboard
uvicorn web.app:app --reload --port 8000
```

### Environment for development

```ini
DEBUG=true
LOG_LEVEL=DEBUG
DOMAIN=localhost
```

---

## 📊 Redis Key Schema

| Key Pattern | TTL | Purpose |
|-------------|-----|---------|
| `flood:{group}:{user}` | `flood_window_secs` | Message counter |
| `topic_restricted:{group}:{thread}` | 5 min | Restriction cache |
| `topic_allowed:{group}:{thread}:{user}` | 5 min | Whitelist cache |
| `mod_settings:{group}` | 10 min | Settings cache |
| `captcha:{group}:{user}` | 5 min | Pending captcha |
| `session:{token}` | 24h | Dashboard session |

---

## 🔐 Security Notes

- All secrets in `.env` — never committed to git (`.gitignore` includes it)
- Dashboard sessions stored in Redis (not cookies) — revocable
- Telegram Login Widget verified with HMAC-SHA256
- Nginx rate-limits login and API endpoints
- Non-root Docker user (`botuser`)
- PostgreSQL and Redis bound to `127.0.0.1` only
- HSTS enabled with 1-year max-age
- TLS 1.2/1.3 only with hardened cipher suite

---

## 📈 Extending the Bot

### Add a new moderation feature

1. Add a column to `ModerationSettings` in `core/models/database.py`
2. Create a new Alembic migration: `alembic revision --autogenerate -m "add_X"`
3. Add the handler in `bot/handlers/` and register the router in `bot/main.py`
4. Add the toggle in `web/templates/dashboard/group_settings.html`

### Add a new group

Just add the bot to a Telegram group and make it an admin. The `group_setup.py` handler auto-registers it.

---

## 📜 License

MIT License — free to use, modify, and distribute.
