# DEPLOYMENT.md

## Deployment Guide

### 1. Variabili ambiente
```
BOT_TOKEN=xxxx
DB_URL=sqlite:///db.sqlite3
SECRET_KEY=xxxxx
```

### 2. Avvio con Docker
```
docker compose up -d
```

### 3. Reverse proxy consigliati
- Caddy (HTTPS automatico)
- Nginx

### 4. Deploy suggeriti
- VPS (DigitalOcean / Hetzner)
- Railway.app
- Fly.io
- Koyeb