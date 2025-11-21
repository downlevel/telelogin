# Security Model

## Overview

TeleLogin uses Telegram as a second factor for authentication, providing a more secure alternative to traditional password-based systems or email/SMS OTP.

---

## 1. Initial Association (Username ↔ Telegram ID)

### Security Mechanism
The initial link between a local username and Telegram ID is established through a cryptographically secure process:

- **Token Generation**: Short URL-safe token (32 bytes from `secrets.token_urlsafe`)
- **Server-Side Storage**: Token metadata stored with user_id and expiration
- **Deep Link Delivery**: Token embedded in Telegram deep link
- **Bot Verification**: Bot receives token directly from Telegram client
- **Single Use**: Token invalidated after successful linking

### Why This Is Secure
- **No Client-Side Token Handling**: Token never passes through user's browser after initial link generation
- **Telegram Origin Guarantee**: Only Telegram app can trigger `/start` command with deep link parameter
- **Prevents ID Spoofing**: Attacker cannot claim arbitrary telegram_id without token
- **Time-Limited**: Tokens expire after 30 minutes
- **One-Time Use**: Token invalidated immediately after successful link

### Attack Resistance
- ❌ **Man-in-the-Middle**: Token only valid for one telegram_id (the one clicking the link)
- ❌ **Token Reuse**: Token marked as used after first successful link
- ❌ **Brute Force**: 32-byte token space (2^256 possibilities)

---

## 2. Login Authentication via Bot

### Two-Factor Authentication Model
TeleLogin provides inherent 2FA:
1. **Knowledge Factor**: User knows their username
2. **Possession Factor**: User possesses device with Telegram access

### Login Confirmation Flow Security

**Notification Delivery:**
- Bot sends message directly to user's Telegram via chat_id
- Only the legitimate user receives the confirmation request
- Telegram's infrastructure ensures message reaches correct recipient

**Confirmation Mechanism:**
- User must physically click Confirm/Deny button
- Bot verifies telegram_id matches the linked account
- Backend validates login_request hasn't been used or expired

**Advantages over Email/SMS OTP:**
- ✅ **No Phone Number Required**: No SIM swap attacks
- ✅ **No Email Compromise**: Email account breach doesn't grant access
- ✅ **Real-Time Notification**: Instant delivery via Telegram's push system
- ✅ **Active Confirmation**: User must actively approve (not just receive code)
- ✅ **Denial Capability**: User can explicitly deny unauthorized attempts

---

## 3. Token and Session Management

### Registration Tokens
- **Type**: Short URL-safe strings (32 bytes)
- **Storage**: In-memory dictionary (consider Redis for production)
- **Lifespan**: 30 minutes (configurable)
- **Single-Use**: Marked as used after successful link
- **Metadata**: Includes user_id, type, expiration timestamp

### Login Request IDs
- **Type**: UUID4 (128-bit random identifier)
- **Storage**: SQLite database with foreign key to user
- **States**: pending → approved/denied
- **One-Time Use**: Cannot be reused after confirmation

### Session Tokens (JWT)
- **Algorithm**: HS256 (HMAC with SHA-256)
- **Claims**: 
  - `sub`: username
  - `user_id`: internal user ID
  - `exp`: expiration timestamp
- **Signing Key**: `SECRET_KEY` environment variable
- **Expiration**: Configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`

**JWT Security Considerations:**
- Tokens are stateless (no server-side session tracking)
- Revocation requires changing `SECRET_KEY` (affects all users)
- For production, consider:
  - Token blacklist for individual revocation
  - Refresh token mechanism
  - Short expiration times (15-60 minutes)

---

## 4. Data Privacy

### Minimal Data Collection
TeleLogin follows privacy-by-design principles:

**What We Store:**
- ✅ Local username (application-specific)
- ✅ Telegram user ID (numeric identifier)
- ✅ Timestamps (created_at, linked_at)
- ✅ Login request status

**What We Don't Store:**
- ❌ Telegram username (@handle)
- ❌ Phone number
- ❌ Profile photo
- ❌ Real name
- ❌ Email address
- ❌ Passwords

### GDPR Compliance Considerations
- Users can delete their Telegram link (implement account deletion endpoint)
- Minimal personal data reduces compliance scope
- telegram_id alone is not personally identifiable without Telegram cooperation

---

## 5. Threat Model

### Protected Against

✅ **Credential Stuffing**
- No passwords to steal or reuse
- Each login requires active Telegram confirmation

✅ **Phishing**
- Even if user is tricked into providing username, attacker needs Telegram access
- User receives real-time notification of login attempt

✅ **Session Hijacking**
- JWT tokens have expiration
- Can be revoked by changing SECRET_KEY

✅ **SIM Swap Attacks**
- No phone number involved in authentication
- Telegram account protected by Telegram's own 2FA

✅ **Email Account Compromise**
- No email involved in login process

### Attack Vectors to Consider

⚠️ **Device Theft**
- If attacker has physical access to unlocked device with Telegram
- Mitigation: Encourage Telegram's built-in passcode lock

⚠️ **Telegram Account Compromise**
- If attacker gains access to user's Telegram account
- Mitigation: Encourage Telegram 2FA (Cloud Password)

⚠️ **Malicious Bot Impersonation**
- User might click link to wrong bot
- Mitigation: Clearly display bot username, verify blue checkmark

⚠️ **Token Interception**
- Registration link shared via insecure channel
- Mitigation: Links expire quickly, one-time use

---

## 6. Production Security Enhancements

### Recommended Additions

**Rate Limiting:**
```python
# Limit login attempts per username
# Limit registration per IP
# Prevent notification spam
```

**Audit Logging:**
```python
# Log all authentication events
# Track failed login attempts
# Monitor for suspicious patterns
```

**Token Revocation:**
```python
# Implement blacklist for individual JWT revocation
# Add user-initiated session termination
# Track active sessions per user
```

**Account Management:**
```python
# Allow user to unlink Telegram account
# Implement account deletion (GDPR right to erasure)
# Show login history to users
```

**Network Security:**
```python
# Use HTTPS only (enforce in production)
# Implement CORS policies
# Add security headers (HSTS, CSP, etc.)
```

**Database Security:**
```python
# Encrypt sensitive fields at rest
# Use parameterized queries (already done)
# Regular backups with encryption
# Restrict database file permissions
```

---

## 7. Cryptographic Primitives

### Token Generation
- **Function**: `secrets.token_urlsafe(32)`
- **Entropy**: 256 bits
- **Character Set**: URL-safe base64
- **CSPRNG**: Operating system's secure random source

### JWT Signing
- **Algorithm**: HS256 (HMAC-SHA256)
- **Key Source**: `SECRET_KEY` environment variable
- **Library**: PyJWT 2.8.0

### Password Hashing (if passwords added)
- **Recommended**: bcrypt via passlib
- **Work Factor**: 12+ rounds
- **Never store plaintext**

---

## 8. Security Checklist

### Development
- [ ] Use environment variables for secrets
- [ ] Never commit `.env` file
- [ ] Use `.gitignore` for sensitive files
- [ ] Review dependencies for vulnerabilities

### Deployment
- [ ] Generate strong SECRET_KEY (32+ random chars)
- [ ] Use HTTPS in production
- [ ] Set `DEBUG=false`
- [ ] Restrict database file permissions (chmod 600)
- [ ] Enable firewall on VPS
- [ ] Use principle of least privilege for system user

### Operations
- [ ] Regular backups of database
- [ ] Monitor logs for suspicious activity
- [ ] Keep dependencies updated
- [ ] Have incident response plan
- [ ] Document security procedures

---

## 9. Responsible Disclosure

If you discover a security vulnerability, please:
1. **Do not** open a public issue
2. Email security details to: [your-email@domain.com]
3. Allow reasonable time for patch before disclosure
4. We appreciate responsible disclosure and will credit researchers

---

## 10. References

- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [Telegram Bot API Security](https://core.telegram.org/bots/api#authorizing-your-bot)
- [JWT Best Practices](https://datatracker.ietf.org/doc/html/rfc8725)
- [Python Secrets Module](https://docs.python.org/3/library/secrets.html)
