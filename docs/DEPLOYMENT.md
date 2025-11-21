# Deployment Guide

## Environment Variables

Create a `.env` file in the project root with the following variables:

```env
# Telegram Bot Configuration
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
BOT_USERNAME=YourBotUsername

# Database
DB_URL=sqlite:///data/db.sqlite3

# Security
SECRET_KEY=your-secret-key-min-32-characters-long

# API Configuration
API_PORT=8000
DEBUG=false
```

### Required Variables
- `BOT_TOKEN`: Get from [@BotFather](https://t.me/botfather) on Telegram
- `BOT_USERNAME`: Your bot's username (without @)
- `SECRET_KEY`: Random string for JWT signing (min 32 characters)

### Optional Variables
- `DB_URL`: Database path (default: `sqlite:///data/db.sqlite3`)
- `API_PORT`: API server port (default: `8000`)
- `DEBUG`: Enable debug logging (default: `false`)

---

## Deployment with Docker

### 1. Build and start containers

```bash
docker compose up -d
```

This starts two services:
- **api**: FastAPI backend on port 8000
- **bot**: Telegram bot with notification server on port 8001 (internal)

### 2. View logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f bot
```

### 3. Stop containers

```bash
docker compose down
```

### 4. Rebuild after code changes

```bash
docker compose down
docker compose build
docker compose up -d
```

---

## Local Development (without Docker)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

Create `.env` file or export variables:

```bash
export BOT_TOKEN=your_token
export BOT_USERNAME=YourBot
export SECRET_KEY=your_secret_key
export DB_URL=sqlite:///db.sqlite3
```

### 3. Start API server

```bash
uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Start Bot (in another terminal)

```bash
python -m src.bot
```

---

## Production Deployment

### Reverse Proxy

Use a reverse proxy for HTTPS:

**Nginx:**
```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Caddy (automatic HTTPS):**
```
api.yourdomain.com {
    reverse_proxy localhost:8000
}
```

### Platform Recommendations

- **VPS**: DigitalOcean, Hetzner, Linode
- **PaaS**: Railway.app, Fly.io, Render.com
- **Container**: Any Docker-compatible platform

### Security Checklist

- [ ] Set strong `SECRET_KEY` (32+ random characters)
- [ ] Use HTTPS in production (reverse proxy with SSL)
- [ ] Set `DEBUG=false` in production
- [ ] Restrict database file permissions
- [ ] Use environment variables (never commit `.env`)
- [ ] Enable firewall on VPS
- [ ] Regular backups of SQLite database

---

## Database Backup

SQLite database file location: `/app/data/db.sqlite3` (in Docker) or `./db.sqlite3` (local)

**Backup command:**
```bash
# Docker
docker cp telelogin-api-1:/app/data/db.sqlite3 ./backup.sqlite3

# Local
cp db.sqlite3 backup-$(date +%Y%m%d).sqlite3
```