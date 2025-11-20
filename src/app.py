"""
Backend API entrypoint
FastAPI application main file
"""
from fastapi import FastAPI
from contextlib import asynccontextmanager
from src.web.routes import router
from src.config import settings
from src.database.sqlite import SQLiteDatabase

# Initialize database
db = SQLiteDatabase()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database tables
    await db.init_db()
    yield
    # Shutdown: cleanup if needed

app = FastAPI(
    title="TeleLogin",
    description="Telegram-based authentication system",
    version="1.0.0",
    lifespan=lifespan
)

# Include routes
app.include_router(router)

@app.get("/")
async def root():
    return {"message": "TeleLogin API", "status": "running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
