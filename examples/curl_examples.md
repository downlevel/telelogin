# TeleLogin cURL Examples

## Register a new user

```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"username": "mario92"}'
```

**Response:**
```json
{
  "link": "https://t.me/YourBot?start=TOKEN"
}
```

---

## Start login process

```bash
curl -X POST http://localhost:8000/auth/start-login \
  -H "Content-Type: application/json" \
  -d '{"username": "mario92"}'
```

**Response:**
```json
{
  "login_id": "uuid-here",
  "status": "pending"
}
```

---

## Check login status

```bash
curl http://localhost:8000/status/uuid-here
```

**Response:**
```json
{
  "status": "pending"
}
```

Possible status values: `pending`, `approved`, `denied`, `expired`

---

## Confirm login (called by bot)

```bash
curl -X POST http://localhost:8000/auth/confirm-login \
  -H "Content-Type: application/json" \
  -d '{
    "login_id": "uuid-here",
    "telegram_id": 123456789
  }'
```

**Response:**
```json
{
  "status": "authenticated",
  "session_token": "jwt-token-here"
}
```
