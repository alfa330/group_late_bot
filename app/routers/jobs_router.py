import logging

from fastapi import APIRouter

from app.config import settings
from app.services.lateness_service import poll_workpace

logger = logging.getLogger(__name__)
router = APIRouter()


@router.api_route("/jobs/poll-workpace", methods=["GET", "HEAD"])
async def poll_workpace_job(secret: str = ""):
    if secret != settings.cron_secret:
        return {"ok": False, "error": "Unauthorized"}
    result = await poll_workpace()
    return result
