# Authentication Flow Overview

Complete step-by-step flow for registration and login processes.

---

## 🔹 Registration Flow

**Goal**: Link a username to a Telegram account

### Step-by-Step Process

1. **User Registration**
   - User provides a username via web interface/API
   - Client calls `POST /register` with username

2. **Token Generation**
   - Backend creates user in database
   - Generates short URL-safe token (32 characters)
   - Stores token metadata (user_id, expiration, type)
   - Returns Telegram deep link: `https://t.me/BotUsername?start=TOKEN&startattach=reply`

3. **User Opens Telegram**
   - User clicks the registration link
   - Telegram app opens the bot
   - User sees "START" button (if first time using bot)

4. **Bot Receives Token**
   - User clicks START button
   - Telegram sends `/start TOKEN` to bot
   - Bot extracts token from command arguments

5. **Account Linking**
   - Bot calls `POST /auth/link-telegram` with:
     - `token`: Registration token
     - `telegram_id`: User's Telegram ID
   - Backend verifies token validity
   - Updates user record with `telegram_id`
   - Marks token as used

6. **Confirmation**
   - Bot sends success message to user
   - User can now use Telegram for login authentication

**Important Notes:**
- Token is single-use only
- Token expires after 30 minutes (configurable)
- If user already started bot before, they must delete chat and click link again, or use `/link TOKEN` command

---

## 🔹 Login Flow

**Goal**: Authenticate user via Telegram confirmation

### Step-by-Step Process

1. **Login Initiation**
   - User enters username in login form
   - Client calls `POST /auth/start-login` with username

2. **Login Request Creation**
   - Backend verifies user exists and has linked Telegram
   - Creates login_request with unique UUID
   - Sets status to `pending`
   - Returns `login_id` to client

3. **Bot Notification**
   - Backend calls bot's HTTP endpoint: `POST http://bot:8001/notify-login`
   - Sends: `telegram_id`, `login_id`, `username`
   - Bot receives notification via internal HTTP server

4. **User Notification**
   - Bot sends message to user via Telegram:
     ```
     🔐 Login Request
     
     Username: mario92
     
     Do you want to confirm this login?
     [✅ Confirm] [🚫 Deny]
     ```

5. **Status Polling**
   - Client polls `GET /status/{login_id}` every 2 seconds
   - Initial response: `{"status": "pending"}`

6. **User Decision**
   
   **If user clicks ✅ Confirm:**
   - Bot calls `POST /auth/confirm-login` with `login_id` and `telegram_id`
   - Backend verifies telegram_id matches the user
   - Generates JWT session token
   - Updates login_request: status = `approved`, stores session_token
   - Bot updates message: "✅ Login confirmed successfully!"
   
   **If user clicks 🚫 Deny:**
   - Bot updates login_request: status = `denied`
   - Bot updates message: "🚫 Login request denied"

7. **Login Completion**
   - Client's next poll receives:
     ```json
     {
       "status": "approved",
       "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
     }
     ```
   - Client stores session token in localStorage/sessionStorage
   - Client uses token in Authorization header for authenticated requests

---

## 🔹 Architecture Diagram

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│   Client    │         │   FastAPI   │         │ Telegram Bot│
│  (Browser)  │         │   Backend   │         │   Service   │
└──────┬──────┘         └──────┬──────┘         └──────┬──────┘
       │                       │                       │
       │  POST /register       │                       │
       ├──────────────────────>│                       │
       │  {username}           │                       │
       │                       │                       │
       │  Registration link    │                       │
       │<──────────────────────┤                       │
       │                       │                       │
       │  [User clicks link → Telegram opens]         │
       │                                               │
       │                                  /start TOKEN │
       │                                      ┌────────┤
       │                                      │        │
       │                       POST           │        │
       │                  /auth/link-telegram │        │
       │                       <───────────────┘        │
       │                       │                       │
       │  POST /auth/start-login                      │
       ├──────────────────────>│                       │
       │  {username}           │                       │
       │                       │                       │
       │  {login_id}           │  POST /notify-login   │
       │<──────────────────────┤──────────────────────>│
       │                       │  {telegram_id,        │
       │                       │   login_id}           │
       │                       │                       │
       │                       │       Send message    │
       │                       │       with buttons ───┤
       │                       │                       │ [User sees notification]
       │  GET /status/{id}     │                       │
       ├──────────────────────>│                       │
       │  {status: pending}    │                       │
       │<──────────────────────┤                       │
       │                       │                       │
       │  (polling...)         │                       │
       │                       │                       │ [User clicks Confirm]
       │                       │  POST /auth/confirm   │
       │                       │<──────────────────────┤
       │                       │  {login_id}           │
       │                       │                       │
       │  GET /status/{id}     │  Success message ────>│
       ├──────────────────────>│                       │
       │  {status: approved,   │                       │
       │   session_token}      │                       │
       │<──────────────────────┤                       │
       │                       │                       │
       │  [Authenticated]      │                       │
       │                       │                       │
```

---

## 🔹 Security Considerations

1. **Initial Association (username ↔ Telegram ID)**
   - Only established via signed token from bot
   - Guarantees authenticity from Telegram
   - Prevents Telegram ID spoofing

2. **Login Confirmation via Bot**
   - Notification sent through Telegram bot ensures:
     - Real control of user's device
   - More secure than OTP via email/SMS
   - User must physically approve each login

3. **Single-Use Tokens**
   - Registration tokens expire after use
   - Tokens have time-based expiration
   - Login IDs are not reusable

4. **No Sensitive Data Collection**
   - No Telegram username, photos, or full name stored
   - Only `telegram_id` and local username
   - Minimal data footprint

5. **Session Management**
   - JWT tokens for stateless authentication
   - Tokens include user_id and username claims
   - Can be revoked by changing SECRET_KEY (affects all sessions)