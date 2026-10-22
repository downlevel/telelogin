"""
Backend API entrypoint
FastAPI application main file
"""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi.responses import HTMLResponse
from src.web.dependencies import get_db
from src.web.security import RateLimiter
from fastapi import Depends

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database.sqlite import SQLiteDatabase
from src.web.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database tables
    app.state.db = SQLiteDatabase()
    await app.state.db.init_db()
    app.state.limiter = RateLimiter()
    app.state.login_html = Path(__file__).with_name("web").joinpath("templates/index.html").read_text(encoding="utf-8")
    yield
    # Shutdown: cleanup if needed

app = FastAPI(
    title="TeleLogin",
    description="Telegram-based authentication system",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for browser clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)

@app.get("/")
async def root():
    return {"message": "TeleLogin API", "status": "running"}



@app.get("/login", response_class=HTMLResponse)
async def login():
    return HTMLResponse(app.state.login_html)


@app.get("/health")
async def health(db=Depends(get_db)):
    await db.ping()
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
