# FLOW_OVERVIEW.md

## Overview del flusso di registrazione e login

### 🔹 Registrazione
1. Utente inserisce username
2. Backend genera TOKEN
3. Link fornito all’utente → `https://t.me/bot?start=TOKEN`
4. L’utente apre il bot
5. Bot invia TOKEN al backend
6. Backend associa username ↔ telegram_id

### 🔹 Login
1. Utente inserisce username
2. Backend crea login_request
3. Bot invia notifica push: "Confermi l’accesso?"
4. Utente clicca **Conferma**
5. Bot chiama backend
6. Backend crea sessione