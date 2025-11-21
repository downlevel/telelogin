# API Reference

Complete API documentation for the TeleLogin FastAPI backend.

### **POST /register**
Register a new user and get a Telegram registration link.

**Request Body:**
```json
{
  "username": "mario92"
}
```
**Response:**
```json
{
  "link": "https://t.me/YourBot?start=SHORT_TOKEN&startattach=reply"
}
```

**Notes:**
- The token in the link is a short URL-safe token (not JWT)
- User must click the link and press START button in Telegram
- Bot receives the token via `/start` command with deep link parameter

---

### **POST /auth/start-login**
Start the login process. Sends a notification to the user's Telegram bot.

**Request Body:**
```json
{
  "username": "mario92"
}
```
**Response:**
```json
{
  "login_id": "44309574-68b6-4a7e-9caa-65214e8cdd96",
  "status": "pending"
}
```

**Notes:**
- User must have already linked their Telegram account via registration
- Bot sends a notification with Confirm/Deny buttons
- Returns HTTP 404 if user not found or Telegram not linked

---

### **POST /auth/link-telegram**
Link a Telegram account to a user. Called by the bot after user clicks registration link.

**Request Body:**
```json
{
  "token": "SHORT_TOKEN",
  "telegram_id": 123456789
}
```
**Response:**
```json
{
  "success": true,
  "message": "Telegram account linked successfully"
}
```

**Notes:**
- This endpoint is called by the bot, not by the client
- Token must be valid and not expired
- Token can only be used once

---

### **POST /auth/confirm-login**
Confirm a login request. Called by the bot when user clicks Confirm button.

**Body:**
```json
{
  "login_id": "uuid",
  "telegram_id": 123456789
}
```

**Risposta:**
```json
{
  "status": "authenticated",
  "session_token": "jwt"
}
```

---

### **GET /status/{login_id}**
Check the status of a login request. Poll this endpoint to wait for user confirmation.

**Response (pending):**
```json
{
  "status": "pending"
}
```

**Response (approved):**
```json
{
  "status": "approved",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response (denied):**
```json
{
  "status": "denied"
}
```

**Possible status values:**
- `pending` - Waiting for user confirmation
- `approved` - User confirmed login (includes session_token)
- `denied` - User denied login request
- `expired` - Login request timed out

**Notes:**
- Client should poll this endpoint every 2-3 seconds
- Session token is only included when status is `approved`
- Use the session token in Authorization header: `Bearer <token>`