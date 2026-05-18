import hashlib
import logging
from datetime import datetime
from typing import Optional, Set

import pytz

from app.config import settings
from app.telegram_client import telegram_client
from app.workpace_client import workpace_client
from app.services.chat_service import chat_service

logger = logging.getLogger(__name__)
TZ = pytz.timezone(settings.timezone)

# In-memory cache for deduplication
# If the server restarts, this will be empty, and it might resend today's events.
sent_events_cache: Set[str] = set()


def _make_event_key(emp_id: str, date: str, start: str, in_mark: str, late: int) -> str:
    raw = f"{emp_id}:{date}:{start}:{in_mark}:{late}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _format_dt(dt_str: Optional[str]) -> str:
    if not dt_str:
        return "—"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(dt_str, fmt)
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            local = dt.astimezone(TZ)
            return local.strftime("%H:%M")
        except ValueError:
            continue
    return dt_str


def build_pending_message(rec: dict) -> str:
    emp_name = rec.get("employeeName") or "—"
    schedule = rec.get("scheduleName") or "—"
    plan = _format_dt(rec.get("workTimeStart"))
    fact = _format_dt(rec.get("inMark"))
    late = rec.get("lateIn", 0)
    location = rec.get("inLocationName") or rec.get("locationName") or "—"

    return (
        "⏰ <b>Опоздание сотрудника</b>\n\n"
        f"👤 Сотрудник: {emp_name}\n"
        f"📅 График: {schedule}\n"
        f"🕐 План: {plan}\n"
        f"🕑 Факт: {fact}\n"
        f"⏱ Опоздание: <b>{late} мин.</b>\n"
        f"📍 Локация: {location}\n\n"
        "📋 Статус: ожидает отбивки"
    )


async def poll_workpace() -> dict:
    threshold = settings.late_threshold_minutes
    now_local = datetime.now(TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)

    try:
        records = await workpace_client.get_all_timetable_spans(start_utc, end_utc)
    except Exception as exc:
        logger.error("Workpace API error: %s", exc)
        return {"ok": False, "error": str(exc)}

    fetched = len(records)
    late_found = 0
    sent = 0

    for rec in records:
        late_in = rec.get("lateIn") or 0
        in_mark = rec.get("inMark")
        emp_id = rec.get("employeeExternalId") or rec.get("employeeId")

        if late_in < threshold or not in_mark or not emp_id:
            continue

        late_found += 1

        event_key = _make_event_key(
            emp_id=emp_id,
            date=rec.get("date", ""),
            start=rec.get("workTimeStart", ""),
            in_mark=in_mark,
            late=late_in,
        )

        if event_key in sent_events_cache:
            continue

        # Send to Telegram
        text = build_pending_message(rec)
        keyboard = {
            "inline_keyboard": [
                [{"text": "✅ Отбито", "callback_data": "review"}]
            ]
        }
        
        chats = chat_service.get_all_chats()
        if not chats:
            logger.warning("No chat IDs configured!")
            continue

        sent_to_any = False
        for chat_id in chats:
            msg_id = await telegram_client.send_message(chat_id, text, keyboard)
            if msg_id:
                sent_to_any = True
                
        if sent_to_any:
            sent_events_cache.add(event_key)
            sent += 1

    return {
        "ok": True,
        "fetched": fetched,
        "late_found": late_found,
        "sent": sent,
        "cache_size": len(sent_events_cache)
    }
