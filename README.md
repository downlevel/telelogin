# TeleLogin

A Telegram-based authentication system that allows users to confirm logins via push notifications from a bot.  
Simple, secure, and designed to be easily integrated into any application.

---

## Table of Contents

1. [Features](#-features)
2. [Requirements](#-requirements)
3. [Project Structure](#-project-structure)
4. [Quick Start](#-quick-start)
5. [Flow Overview](#-flow-overview)
6. [API Reference](#-api-reference)
7. [Database Structure](#-database-structure)
8. [Security Model](#-security-model)
9. [Deployment Guide](#-deployment-guide)
10. [License](#-license)

---

## ✨ Features

- **Telegram push notification login confirmation** - No popups or widgets required
- **Privacy-focused** - No sensitive data collected (only Telegram ID)
- **Modern Python backend** - Built with FastAPI
- **Flexible database support** - SQLite (default) or PostgreSQL
- **Extensible and open-source** - Easy to customize and integrate

---

## 📦 Requirements

- Python 3.10+
- Telegram Bot Token (from BotFather)
- SQLite (default) or PostgreSQL

---

## 📁 Project Structure

```
telelogin/
│
├─ src/
│   ├─ app.py                  # Backend API entrypoint
│   ├─ bot.py                  # Telegram bot
│   ├─ config.py               # Configuration management
│   ├─ database/
│   │     ├─ __init__.py
│   │     ├─ base.py           # Abstract interface (CRUD users)
│   │     ├─ sqlite.py         # SQLite implementation
│   │     └─ postgres.py       # PostgreSQL implementation
│   │
│   ├─ models/
│   │     ├─ user.py           # User model definition
│   │     └─ token.py          # Link token management
│   │
│   ├─ services/
│   │     ├─ auth_service.py   # Login logic + bot notification
│   │     ├─ user_service.py   # User profile functions
│   │     └─ token_service.py  # Token management
│   │
│   ├─ utils/
│   │     ├─ crypto.py         # Token signing, hashing, etc.
│   │     └─ logger.py
│   │
│   └─ web/
│        ├─ routes.py          # API definition (FastAPI)
│        ├─ schemas.py         # Pydantic schemas
│        └─ templates/         # Optional minimal web interface
│
├─ tests/
│   ├─ test_auth.py
│   ├─ test_bot.py
│   ├─ test_database_sqlite.py
│   └─ fixtures/
│
├─ db/
│   ├─ schema.sql              # Database schema
│   └─ migrations/             # Future evolutions
│
├─ docs/
│   ├─ README.md
│   ├─ API_REFERENCE.md
│   ├─ FLOW_DIAGRAM.png
│   ├─ SECURITY.md
│   └─ DEPLOYMENT.md
│
├─ examples/
│   ├─ python_client/
│   ├─ curl_examples.md
│   └─ js_client/
│
├─ docker/
│   ├─ Dockerfile              # Backend build
│   ├─ docker-compose.yml      # Services (API + DB + bot)
│   └─ env.example
│
├─ .env.example                # Environment variables (BOT_TOKEN, DB_URL…)
├─ requirements.txt            # Python dependencies
├─ pyproject.toml              # Optional
├─ LICENSE
└─ README.md
```

---

## 🚀 Quick Start

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
uvicorn src.app:app --reload
```

---

## 🔄 Flow Overview

### Registration Flow

1. **User enters username**
2. **Backend generates TOKEN**
3. **Link provided to user** → `https://t.me/YourBot?start=TOKEN`
4. **User opens the bot**
5. **Bot sends TOKEN to backend**
6. **Backend associates** username ↔ telegram_id

### Login Flow

1. **User enters username**
2. **Backend creates login_request**
3. **Bot sends push notification**: "Confirm access?"
4. **User clicks Confirm**
5. **Bot calls backend**
6. **Backend creates session**

---

## 📡 API Reference

### **POST /register**
Initiates the registration of a new user.

**Request Body:**
```json
{
  "username": "mario92"
}
```

**Response:**
```json
{
  "link": "https://t.me/YourBot?start=TOKEN"
}
```

---

### **POST /auth/start-login**
Starts the login process.

**Request Body:**
```json
{
  "username": "mario92"
}
```

**Response:**
```json
{
  "login_id": "uuid",
  "status": "pending"
}
```

---

### **POST /auth/confirm-login**
Called by the bot when the user confirms.

**Request Body:**
```json
{
  "login_id": "uuid",
  "telegram_id": 123456789
}
```

**Response:**
```json
{
  "status": "authenticated",
  "session_token": "jwt"
}
```

---

### **GET /status/{login_id}**
Allows the client interface to verify the login outcome.

**Response:**
```json
{
  "status": "pending"
}
```

---

## 🗄️ Database Structure

### Table: `users`

| Field        | Type         | Notes                    |
|--------------|--------------|--------------------------|
| id           | INTEGER PK   |                          |
| username     | TEXT UNIQUE  | Local identifier         |
| telegram_id  | INTEGER      | Telegram ID              |
| created_at   | DATETIME     |                          |
| linked_at    | DATETIME     |                          |

---

### Table: `login_requests`

| Field        | Type         | Notes                                 |
|--------------|--------------|---------------------------------------|
| id           | UUID PK      | Login request identifier              |
| user_id      | INT          | FK users.id                           |
| status       | TEXT         | pending / approved / denied / expired |
| created_at   | DATETIME     |                                       |

---

### Recommended Indexes

- `users(username)`
- `users(telegram_id)`
- `login_requests(user_id)`

---

## 🔒 Security Model

### 1. Initial Association: username ↔ Telegram ID
Performed only via a signed token link received by the bot:
- Guarantees Telegram origin
- Prevents ID spoofing

### 2. Login Confirmation via Bot
The notification sent by the bot ensures:
- Real control of the user's device
- More secure than OTP via email/SMS

### 3. Single-Use Tokens
- Registration tokens expire
- Login IDs are not reusable

### 4. No Sensitive Data Collected
- Telegram username, photos, or full name are NOT stored
- Only `telegram_id` and local username

### 5. Possible Security Extensions
- Rate-limit login attempts
- Anomaly logging
- Manual revocation of Telegram association

---

## 🚀 Deployment Guide

### 1. Environment Variables

Create a `.env` file with the following variables:

```bash
BOT_TOKEN=xxxx
DB_URL=sqlite:///db.sqlite3
SECRET_KEY=xxxxx
```

### 2. Start with Docker

```bash
docker compose up -d
```

### 3. Recommended Reverse Proxies

- **Caddy** (automatic HTTPS)
- **Nginx**

### 4. Suggested Deployment Platforms

- VPS (DigitalOcean / Hetzner)
- Railway.app
- Fly.io
- Koyeb

---

## 📄 License

This project is open-source. Please refer to the [LICENSE](LICENSE) file for more details.