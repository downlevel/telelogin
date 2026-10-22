"""
Backend API entrypoint
FastAPI application main file
"""
from contextlib import asynccontextmanager, suppress
import asyncio
import logging
from pathlib import Path
from src.web.dependencies import get_db
from src.web.security import RateLimiter
from fastapi import Depends

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import __version__
from src.config import settings
from src.database.sqlite import SQLiteDatabase
from src.web.routes import router
from src.web.oidc import router as oidc_router, load_key
from src.web.sso import router as sso_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.PUBLIC_URL == "http://localhost:8000" and not settings.DEBUG:
        logging.getLogger(__name__).warning("PUBLIC_URL is still the localhost default with DEBUG=false")
    if settings.PUBLIC_URL.startswith("https:") and not settings.SSO_COOKIE_SECURE:
        logging.getLogger(__name__).warning("PUBLIC_URL uses HTTPS but SSO_COOKIE_SECURE=false")
    # Startup: Initialize database tables
    app.state.db = SQLiteDatabase()
    await app.state.db.init_db()
    app.state.oidc_key = load_key(settings.OIDC_KEY_FILE)
    app.state.limiter = RateLimiter()
    app.state.login_html = Path(__file__).with_name("web").joinpath("templates/index.html").read_text(encoding="utf-8")
    async def purge_once():
        try:
            await app.state.db.purge_old(settings.LOGIN_HISTORY_RETENTION_DAYS * 86400)
        except Exception:
            logging.getLogger(__name__).warning("Retention purge failed")

    async def purge():
        while True:
            await asyncio.sleep(settings.PURGE_INTERVAL_SECONDS)
            await purge_once()

    await purge_once()
    task = asyncio.create_task(purge())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

app = FastAPI(
    title="TeleLogin",
    description="Telegram-based authentication system",
    version=__version__,
    lifespan=lifespan
)

class APICORSMiddleware(CORSMiddleware):
    async def __call__(self, scope, receive, send):
        if scope.get('path', '').startswith('/sso/'):
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)


# Configure CORS for browser clients
app.add_middleware(
    APICORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)
app.include_router(sso_router)
app.include_router(oidc_router)

@app.get("/health")
async def health(db=Depends(get_db)):
    await db.ping()
    return {"status": "ok", "version": __version__}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
