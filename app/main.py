import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.routers.telegram_router import router as telegram_router
from app.routers.jobs_router import router as jobs_router
from app.telegram_client import telegram_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Group Late Bot", docs_url=None, redoc_url=None)

# Routers
app.include_router(telegram_router)
app.include_router(jobs_router)

@app.on_event("startup")
async def on_startup():
    try:
        await telegram_client.set_webhook()
    except Exception as e:
        logging.error(f"Failed to set webhook on startup: {e}")

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"app": "Group Late Bot MVP", "status": "running"}
