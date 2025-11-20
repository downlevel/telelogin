# SECURITY.md

## Modello di Sicurezza

### 1. Associazione iniziale username ↔ Telegram ID
Effettuata solo tramite link con token firmato, ricevuto dal bot:
- garantisce provenienza Telegram
- impedisce spoofing dell’ID

### 2. Conferma login tramite bot
La notifica inviata dal bot garantisce:
- controllo reale del dispositivo dell’utente
- più sicura di un OTP via email/SMS

### 3. Token monouso
- I token di registrazione scadono
- I login id non sono riutilizzabili

### 4. Nessun dato sensibile raccolto
- Non si memorizzano username Telegram, né foto, né nome/cognome
- Solo `telegram_id` e username locale

### 5. Possibili estensioni di sicurezza
- Rate-limit tentativi di login
- Logging anomalie
- Revoca manuale dell’associazione Telegram