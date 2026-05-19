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
sent_events_cache: Set[str] = set()

def _make_event_key(emp_id: str, date: str, event_type: str) -> str:
    raw = f"{emp_id}:{date}:{event_type}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _parse_dt(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
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
            if dt.tzinfo is not None:
                return dt.astimezone(TZ)
            elif fmt.endswith("Z"):
                dt = pytz.utc.localize(dt)
                return dt.astimezone(TZ)
            else:
                return TZ.localize(dt)
        except ValueError:
            continue
    return None

def _format_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.strftime("%H:%M")

def build_missing_message(rec: dict, plan_dt: datetime, now_dt: datetime) -> str:
    emp_name = rec.get("employeeName") or "—"
    schedule = rec.get("scheduleName") or "—"
    plan = _format_dt(plan_dt)
    passed_mins = int((now_dt - plan_dt).total_seconds() / 60)

    return (
        "🚨 <b>Отсутствует на месте</b>\n\n"
        f"👤 Сотрудник: {emp_name}\n"
        f"📅 График: {schedule}\n"
        f"🕐 План: {plan}\n"
        f"🕑 Факт: Нет отметки\n"
        f"⏱ Прошло с начала смены: <b>{passed_mins} мин.</b>\n\n"
        "📋 Статус: ожидает отбивки"
    )

def build_late_message(rec: dict, plan_dt: datetime, fact_dt: datetime, late_mins: int) -> str:
    emp_name = rec.get("employeeName") or "—"
    schedule = rec.get("scheduleName") or "—"
    plan = _format_dt(plan_dt)
    fact = _format_dt(fact_dt)
    location = rec.get("inLocationName") or rec.get("locationName") or "—"

    return (
        "⏰ <b>Фактическое опоздание</b>\n\n"
        f"👤 Сотрудник: {emp_name}\n"
        f"📅 График: {schedule}\n"
        f"🕐 План: {plan}\n"
        f"🕑 Факт: {fact}\n"
        f"⏱ Опоздание: <b>{late_mins} мин.</b>\n"
        f"📍 Локация: {location}\n\n"
        "📋 Статус: ожидает отбивки"
    )

async def poll_workpace() -> dict:
    threshold = settings.late_threshold_minutes
    now_local = datetime.now(TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)

    try:
        records = await workpace_client.get_all_timetable_spans(start_local, end_local)
    except Exception as exc:
        logger.error("Workpace API error: %s", exc)
        return {"ok": False, "error": str(exc)}

    fetched = len(records)
    events_found = 0
    sent = 0

    chats = chat_service.get_all_chats()
    if not chats:
        logger.warning("No chat IDs configured!")
        return {"ok": True, "fetched": fetched, "sent": 0}

    for rec in records:
        emp_id = rec.get("employeeExternalId") or rec.get("employeeId")
        if not emp_id:
            continue

        date_str = rec.get("date", "")
        work_time_start_str = rec.get("workTimeStart")
        in_mark_str = rec.get("inMark")
        late_in = rec.get("lateIn") or 0

        plan_dt = _parse_dt(work_time_start_str)
        if not plan_dt:
            continue

        event_key = None
        text = None

        # Logic: missing or late
        if not in_mark_str:
            # Not arrived yet
            passed_mins = (now_local - plan_dt).total_seconds() / 60
            if passed_mins >= 10:  # Threshold for missing
                event_key = _make_event_key(emp_id, date_str, "missing")
                if event_key not in sent_events_cache:
                    text = build_missing_message(rec, plan_dt, now_local)
        else:
            # Arrived
            if late_in >= threshold:
                event_key = _make_event_key(emp_id, date_str, "late")
                if event_key not in sent_events_cache:
                    fact_dt = _parse_dt(in_mark_str)
                    if fact_dt:
                        text = build_late_message(rec, plan_dt, fact_dt, late_in)

        if text and event_key:
            events_found += 1
            keyboard = {
                "inline_keyboard": [
                    [{"text": "✅ Отбито", "callback_data": "review"}]
                ]
            }
            
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
        "events_found": events_found,
        "sent": sent,
        "cache_size": len(sent_events_cache)
    }
