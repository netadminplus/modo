# 🤖 Modo - Telegram Group Management Bot

A powerful, multi-group Telegram Group Management Bot with a Web Dashboard, specializing in **Forum Topic ACL management** and granular user permissions.

Built with **Aiogram 3.x** (async), **FastAPI**, **PostgreSQL**, **Redis**, and **Docker**.

---

## 📋 Table of Contents

- [Features](#-features)
- [For Bot Owners - Setup Guide](#-for-bot-owners---setup-guide)
- [For Group Admins - Usage Guide](#-for-group-admins---usage-guide)
- [Scenario-Based Use Cases](#-scenario-based-use-cases)
- [Architecture](#-architecture)
- [Development](#-development)

---

## ✨ Features

### 🔒 Forum Topic ACL (Access Control List)
- Restrict specific forum topics to whitelisted users only
- Per-topic user whitelist management
- Automatic message deletion for unauthorized users

### 🛡️ Moderation Tools
- **Anti-flood**: Rate limiting with configurable thresholds
- **Anti-link**: Auto-delete messages with URLs
- **Word Filter**: Block banned words automatically
- **Warn System**: `/warn`, `/warnings`, `/resetwarns`
- **Mute/Ban/Kick**: Quick moderation actions
- **Captcha**: Math challenge for new members

### 📝 Customizable Messages
- Welcome messages
- Farewell messages  
- Warning templates
- Captcha challenges
- All editable via web dashboard

### 🌐 Web Dashboard
- Telegram Login (no password needed)
- Manage all your groups from one place
- Real-time activity logs
- REST API for automation

---

## 🚀 For Bot Owners - Setup Guide

### Prerequisites

- A server with Docker and Docker Compose installed
- A domain name pointing to your server IP
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Step 1: Clone the Repository

```bash
git clone https://github.com/netadminplus/modo.git
cd modo
```

### Step 2: Configure Environment

```bash
cp .env.example .env
nano .env
```

Edit `.env` with your values:

```ini
# Bot Configuration
BOT_TOKEN=123456789:AAF...          # From @BotFather
BOT_USERNAME=your_bot_username       # Without @
ADMIN_IDS=123456789                  # Your Telegram user ID (get from @userinfobot)

# Database
POSTGRES_USER=botadmin
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=telegram_bot
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://botadmin:your_secure_password_here@postgres:5432/telegram_bot

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password_here
REDIS_URL=redis://:your_redis_password_here@redis:6379/0

# Web Dashboard
SECRET_KEY=generate_random_64_char_string_here
DOMAIN=yourdomain.com
WEB_PORT=8000

# Other
DEBUG=false
LOG_LEVEL=INFO
TIMEZONE=UTC
```

**Get your Telegram User ID:** Message [@userinfobot](https://t.me/userinfobot) on Telegram

**Generate SECRET_KEY:** Run `python3 -c "import secrets; print(secrets.token_hex(32))"`

### Step 3: DNS Configuration

Point your domain to your server:

```
Type: A
Name: @ (or yourdomain.com)
Value: YOUR_SERVER_IP
TTL: 300
```

### Step 4: SSL Certificate (First Time Only)

```bash
# Start nginx
docker compose up -d nginx

# Get SSL certificate
docker compose run --rm certbot

# Restart nginx with SSL
docker compose restart nginx
```

### Step 5: Start All Services

```bash
docker compose up -d
```

### Step 6: Verify Everything Works

```bash
# Check all containers are running
docker compose ps

# View bot logs
docker compose logs -f app

# Check health endpoint
curl https://yourdomain.com/health
```

Expected response: `{"status":"ok"}`

### Step 7: Access Web Dashboard

Open `https://yourdomain.com` in your browser and log in with Telegram.

---

## 👥 For Group Admins - Usage Guide

### Adding Bot to Your Group

1. **Find the bot** on Telegram (search for your bot's username)
2. **Add to group**: Go to your group → Group Info → Add Member → Select the bot
3. **Make bot admin**: Group Info → Edit → Administrators → Add Admin → Select bot

### Required Bot Permissions

The bot needs these admin permissions:

- ✅ Delete messages
- ✅ Ban users  
- ✅ Restrict members (mute)
- ✅ Manage topics (for Forum groups)
- ✅ Pin messages (optional)

### Register Your Group

Once the bot is admin in your group:

1. Open the group chat
2. Send: `/register`
3. Bot replies: `✅ Group registered!`
4. Your group now appears in the web dashboard

### Access Group Settings

1. Go to `https://yourdomain.com`
2. Click "Login with Telegram"
3. Authorize the bot
4. Select your group from the dashboard

---

## 📖 Scenario-Based Use Cases

### Scenario 1: Setting Up a Support Forum

**Situation:** You run a customer support group with different topics for different products.

**Setup:**
```
1. Enable Forum Mode in your Telegram group
2. Create topics: "Product A", "Product B", "General"
3. Add bot and make it admin
4. Send /register in the group
5. In dashboard, go to Topics tab
6. Restrict "Product A" topic
7. Whitelist only your Product A support team
```

**Commands:**
```
/restrict_topic          # Lock current topic
/allow_user 123456789    # Allow specific user
/topic_users             # See allowed users
```

**Result:** Only whitelisted support staff can post in Product A topic. Customers can read but not spam.

---

### Scenario 2: Preventing Flood and Spam

**Situation:** Your group gets flooded with messages and links.

**Dashboard Setup:**
1. Go to Group Settings → Moderation
2. Enable "Anti-Flood"
3. Set threshold: 5 messages per 10 seconds
4. Action: Mute for 5 minutes
5. Enable "Anti-Link"
6. Add banned words: "crypto", "investment", "free money"

**Result:** Users who spam or post links get automatically muted. Banned words are auto-deleted.

---

### Scenario 3: Warning System for Rule Breakers

**Situation:** You want a fair warning system before banning.

**Dashboard Setup:**
1. Group Settings → Moderation
2. Set Max Warnings: 3
3. Auto-action: Ban

**In Group:**
```
/warn @username Spamming
/warn @username          # Reply to message
/warnings @username      # Check warning count
/resetwarns @username    # Reset warnings
```

**Flow:**
- 1st warning: User gets warned
- 2nd warning: User gets warned  
- 3rd warning: User is automatically banned

---

### Scenario 4: New Member Verification

**Situation:** Bots and spammers join your group.

**Dashboard Setup:**
1. Group Settings → Moderation
2. Enable "Captcha"
3. Customize welcome message: `Welcome {user_mention}! Solve: {a} + {b} = ?`

**What Happens:**
1. New member joins
2. Bot restricts them (read-only)
3. Bot sends captcha: "Solve: 5 + 3 = ?"
4. User replies: "8"
5. Bot unmutes and welcomes them

**Result:** Bots fail captcha and leave. Real humans pass easily.

---

### Scenario 5: Multi-Group Management

**Situation:** You manage 10 different groups.

**Dashboard Features:**
1. Single login shows all your groups
2. Switch between groups instantly
3. Copy settings from one group to another
4. View activity logs across all groups
5. Bulk actions (coming soon)

**Benefit:** No need to visit each group individually. Manage everything from one dashboard.

---

### Scenario 6: Temporary Restriction

**Situation:** Your group is under attack, need emergency lockdown.

**Quick Actions:**
```
1. Dashboard → Group Settings
2. Toggle "Restrict All Members" 
3. Only admins can post
4. Attack stops immediately
5. Toggle off when safe
```

**Alternative:** Restrict specific topics instead of entire group.

---

### Scenario 7: Custom Message Templates

**Situation:** You want personalized messages in your brand voice.

**Dashboard:**
1. Group Settings → Message Templates
2. Edit any template:
   - Welcome message
   - Warning message
   - Captcha challenge
   - Farewell message

**Variables Available:**
- `{user_mention}` - @username link
- `{user_name}` - Display name
- `{group_title}` - Group name
- `{count}` - Warning count
- `{max}` - Max warnings
- `{reason}` - Warning reason
- `{duration}` - Mute duration

**Example:**
```
Welcome {user_mention} to {group_title}! 
Please read the rules and enjoy your stay.
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Network                       │
│                                                         │
│  ┌──────────┐    ┌─────────────────────────────────┐   │
│  │  Nginx   │───▶│         App Container           │   │
│  │ (Proxy)  │    │  ┌─────────┐  ┌──────────────┐  │   │
│  └──────────┘    │  │   Bot   │  │  Web Dashboard│  │   │
│       │          │  │(Aiogram)│  │   (FastAPI)  │  │   │
│  ┌────▼─────┐   │  └────┬────┘  └──────┬───────┘  │   │
│  │ Certbot  │   │       │              │          │   │
│  │  (SSL)   │   │       └──────┬───────┘          │   │
│  └──────────┘   │              │                  │   │
│                 │       ┌──────▼──────┐           │   │
│                 │       │ Core Layer  │           │   │
│                 │  ┌────┴─────┐  ┌────┴──────┐    │   │
│                 │  │PostgreSQL│  │  Redis    │    │   │
│                 │  │  (Data)  │  │  (Cache)  │    │   │
│                 │  └──────────┘  └───────────┘    │   │
└─────────────────────────────────────────────────────────┘
```

---

## 🛠️ Development

### Local Development Setup

```bash
# Clone and setup
git clone https://github.com/netadminplus/modo.git
cd modo
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# Start databases
docker compose up -d postgres redis

# Run migrations
alembic upgrade head

# Start bot (terminal 1)
python -m bot.main polling

# Start web dashboard (terminal 2)
uvicorn web.app:app --reload --port 8000
```

### Environment for Development

```ini
DEBUG=true
LOG_LEVEL=DEBUG
DOMAIN=localhost
```

### Running Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "add_feature"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

---

## 📊 Tech Stack

| Component | Technology |
|-----------|------------|
| Bot Framework | Aiogram 3.x |
| Web Framework | FastAPI |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Web Server | Nginx |
| SSL | Let's Encrypt (Certbot) |
| Container | Docker + Docker Compose |
| ORM | SQLAlchemy 2.0 |
| Templates | Jinja2 |

---

## 🔐 Security

- All secrets in `.env` (never committed)
- Dashboard sessions in Redis (revocable)
- Telegram Login verified with HMAC-SHA256
- Nginx rate-limits login and API
- Non-root Docker user
- Database bound to localhost only
- HSTS + TLS 1.2/1.3 only

---

## 📜 License

MIT License — free to use, modify, and distribute.

---

## 🆘 Support

- **Issues:** [GitHub Issues](https://github.com/netadminplus/modo/issues)
- **Discussions:** [GitHub Discussions](https://github.com/netadminplus/modo/discussions)

---

## 🎯 Quick Command Reference

### Bot Commands

| Command | Description |
|---------|-------------|
| `/register` | Register current group |
| `/settings` | Open web dashboard |
| `/warn` | Warn a user |
| `/warnings` | Check user warnings |
| `/resetwarns` | Reset user warnings |
| `/mute` | Temporarily mute user |
| `/ban` | Ban user |
| `/kick` | Kick user |
| `/restrict_topic` | Lock current topic |
| `/unrestrict_topic` | Unlock topic |
| `/allow_user` | Whitelist user in topic |
| `/deny_user` | Remove from whitelist |
| `/topic_users` | List allowed users |

---

Made with ❤️ by [NetAdminPlus](https://github.com/netadminplus)
