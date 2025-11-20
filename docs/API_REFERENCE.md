# API_REFERENCE.md

## API Reference
Tutte le API offerte dal backend FastAPI.

### **POST /register**
Inizia la registrazione di un nuovo utente.

**Body:**
```json
{
  "username": "mario92"
}
```
**Risposta:**
```json
{
  "link": "https://t.me/YourBot?start=TOKEN"
}
```

---

### **POST /auth/start-login**
Avvia il processo di login.

**Body:**
```json
{
  "username": "mario92"
}
```
**Risposta:**
```json
{
  "login_id": "uuid",
  "status": "pending"
}
```

---

### **POST /auth/confirm-login**
Chiamato dal bot quando l’utente conferma.

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
Permette all’interfaccia client di verificare l’esito del login.

**Risposta:**
```json
{
  "status": "pending"
}
```