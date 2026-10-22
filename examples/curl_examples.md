# TeleLogin cURL Examples

Complete examples of all API endpoints using cURL.

---

## 1. Register a new user

```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"username": "mario92"}'
```

**Response:**
```json
{
  "link": "https://t.me/YourBot?start=Xy9P2kR4mNqW8vTa1cBdLfGh5JuKpQsZ3xYzAbCdEfGh"
}
```

**Next steps:**
1. Click the link to open Telegram
2. Press the START button in the bot
3. Bot will confirm registration

---

## 2. Link Telegram account (called by bot)

This endpoint is called by the bot, not by the client directly.

```bash
curl -X POST http://localhost:8000/auth/link-telegram \
  -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "token": "Xy9P2kR4mNqW8vTa1cBdLfGh5JuKpQsZ3xYzAbCdEfGh",
    "telegram_id": 123456789
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "Telegram account linked successfully"
}
```

---

## 3. Start login process

```bash
curl -X POST http://localhost:8000/auth/start-login \
  -H "Content-Type: application/json" \
  -d '{"username": "mario92"}'
```

**Response:**
```json
{
  "login_id": "44309574-68b6-4a7e-9caa-65214e8cdd96",
  "status": "pending",
  "verification_code": 42
}
```

**What happens next:**
- User receives notification in Telegram bot
- User must select the browser code (42 in this example) or 🚫 Deny
- Client should poll `POST /auth/status` endpoint

---

## 4. Check login status (polling)

```bash
curl -X POST http://localhost:8000/auth/status \
  -H "Content-Type: application/json" \
  -d '{"login_id":"44309574-68b6-4a7e-9caa-65214e8cdd96"}'
```

**Response (pending):**
```json
{
  "status": "pending"
}
```

**Response (approved - includes session token):**
```json
{
  "status": "approved",
  "session_token": "ACCESS_JWT",
  "refresh_token": "RANDOM_REFRESH_SECRET"
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
- `approved` - User confirmed, session_token included
- `denied` - User rejected login
- `expired` - Login request timed out

**Polling recommendation:**
- Poll every 2-3 seconds
- Set timeout (60 seconds recommended)
- Stop polling when status is not `pending`

---

## 5. Confirm login (called by bot)

This endpoint is called by the bot when the user selects the browser code.

```bash
curl -X POST http://localhost:8000/auth/confirm-login \
  -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "login_id": "44309574-68b6-4a7e-9caa-65214e8cdd96",
    "telegram_id": 123456789,
    "verification_code": 42
  }'
```

**Response:**
```json
{
  "status": "authenticated"
}
```

---

## 6. Using authenticated requests

Once you have the session token, include it in the Authorization header:

```bash
curl http://localhost:8000/protected-endpoint \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

## Complete Login Flow Example

```bash
#!/bin/bash

# Step 1: Register
echo "Registering user..."
REGISTER_RESPONSE=$(curl -s -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser"}')

echo "Registration link: $(echo $REGISTER_RESPONSE | jq -r '.link')"
echo "Click the link and press START in Telegram bot"
echo ""

# Wait for user to complete registration
read -p "Press enter after linking Telegram account..."

# Step 2: Start login
echo "Starting login..."
LOGIN_RESPONSE=$(curl -s -X POST http://localhost:8000/auth/start-login \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser"}')

LOGIN_ID=$(echo $LOGIN_RESPONSE | jq -r '.login_id')
echo "Login ID: $LOGIN_ID"
echo "Check your Telegram for confirmation request"
echo ""

# Step 3: Poll for status
echo "Polling for login status..."
while true; do
  STATUS_RESPONSE=$(curl -s -X POST http://localhost:8000/auth/status -H "Content-Type: application/json" -d "{\"login_id\":\"$LOGIN_ID\"}")
  STATUS=$(echo $STATUS_RESPONSE | jq -r '.status')

  echo "Status: $STATUS"

  if [ "$STATUS" = "approved" ]; then
    SESSION_TOKEN=$(echo $STATUS_RESPONSE | jq -r '.session_token')
    echo ""
    echo "✅ Login successful!"
    echo "Session token: $SESSION_TOKEN"
    break
  elif [ "$STATUS" = "denied" ]; then
    echo ""
    echo "❌ Login denied"
    exit 1
  elif [ "$STATUS" = "expired" ]; then
    echo ""
    echo "❌ Login expired"
    exit 1
  fi

  sleep 2
done
```

**Save as `login_test.sh` and run:**
```bash
chmod +x login_test.sh
./login_test.sh
```

---

## Testing with Docker

If using Docker deployment:

```bash
# Use Docker host IP instead of localhost
API_URL="http://localhost:8000"

# Or if accessing from another container
API_URL="http://api:8000"

curl -X POST $API_URL/register \
  -H "Content-Type: application/json" \
  -d '{"username": "mario92"}'
```

### Deny login (called by bot)

Deny requires the login ID and sender's Telegram ID, without a verification code.

```bash
curl -X POST http://localhost:8000/auth/deny-login \
  -H "X-Internal-Key: $INTERNAL_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"login_id":"44309574-68b6-4a7e-9caa-65214e8cdd96","telegram_id":123456789}'
```

### Sessions (Phase 3)

Show the `verification_code` from start-login to the user, then retrieve both
`session_token` and `refresh_token` from the first approved status response.

```bash
curl -H "Authorization: Bearer $ACCESS_TOKEN" http://localhost:8000/auth/me
curl -X POST -H 'Content-Type: application/json' \
  -d '{"refresh_token":"REPLACE_WITH_REFRESH_TOKEN"}' http://localhost:8000/auth/refresh
curl -X POST -H "Authorization: Bearer $ACCESS_TOKEN" http://localhost:8000/auth/logout
curl -X POST -H "Authorization: Bearer $ACCESS_TOKEN" http://localhost:8000/auth/logout-all
```

Store both replacement tokens after refreshing. Never refresh concurrently with the
same token: reuse revokes the session. Logout invalidates access immediately.
