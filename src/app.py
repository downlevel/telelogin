"""
Backend API entrypoint
FastAPI application main file
"""
from fastapi import FastAPI
from src.web.routes import router
from src.config import settings

app = FastAPI(
    title="TeleLogin",
    description="Telegram-based authentication system",
    version="1.0.0"
)

# Include routes
app.include_router(router)

@app.get("/")
async def root():
    return {"message": "TeleLogin API", "status": "running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
