import hashlib
import logging
from datetime import datetime
from typing import Optional, Set

import pytz

from app.config import settings
from app.telegram_client import telegram_client
from app.workpace_client import workpace_client
from app.services.chat_service import chat_service
from app.services.mute_service import mute_service

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

def build_early_out_message(rec: dict, plan_end_dt: datetime, fact_out_dt: datetime, early_mins: int) -> str:
    emp_name = rec.get("employeeName") or "—"
    schedule = rec.get("scheduleName") or "—"
    plan = _format_dt(plan_end_dt)
    fact = _format_dt(fact_out_dt)
    location = rec.get("outLocationName") or rec.get("locationName") or "—"

    return (
        "🏃 <b>Ранний уход</b>\n\n"
        f"👤 Сотрудник: {emp_name}\n"
        f"📅 График: {schedule}\n"
        f"🕐 Конец смены: {plan}\n"
        f"🕑 Ушел: {fact}\n"
        f"⏱ Ушел раньше на: <b>{early_mins} мин.</b>\n"
        f"📍 Локация: {location}\n\n"
        "📋 Статус: ожидает отбивки"
    )

def build_missing_out_message(rec: dict, plan_end_dt: datetime, now_dt: datetime) -> str:
    emp_name = rec.get("employeeName") or "—"
    schedule = rec.get("scheduleName") or "—"
    plan = _format_dt(plan_end_dt)
    passed_mins = int((now_dt - plan_end_dt).total_seconds() / 60)

    return (
        "🚨 <b>Нет отметки об уходе</b>\n\n"
        f"👤 Сотрудник: {emp_name}\n"
        f"📅 График: {schedule}\n"
        f"🕐 Конец смены: {plan}\n"
        f"🕑 Факт: Нет отметки\n"
        f"⏱ Прошло с конца смены: <b>{passed_mins} мин.</b>\n\n"
        "📋 Статус: ожидает отбивки"
    )

def build_suspicious_mark_message(mark: dict) -> str:
    emp_name = mark.get("employeeName") or "—"
    dept = mark.get("departmentName") or "—"
    mark_dt = _parse_dt(mark.get("markDate"))
    fact = _format_dt(mark_dt)
    
    mtype_val = mark.get("markType")
    mtype = "Вход" if mtype_val == 0 else "Выход" if mtype_val == 1 else "—"
    device = mark.get("deviceName") or "—"

    return (
        "⚠️ <b>Подозрительная отметка</b>\n\n"
        f"👤 Сотрудник: {emp_name}\n"
        f"🏢 Отдел: {dept}\n"
        f"🕒 Время: {fact}\n"
        f"🔄 Тип: {mtype}\n"
        f"📱 Устройство: {device}\n\n"
        "📋 Статус: ожидает отбивки"
    )

async def poll_workpace() -> dict:
    threshold = settings.late_threshold_minutes
    now_local = datetime.now(TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)

    try:
        records = await workpace_client.get_all_timetable_spans(start_local, end_local)
        marks = await workpace_client.get_all_domain_marks(start_local, end_local)
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

    # Group raw marks by employeeId for easy lookup
    emp_raw_marks = {}
    for m in marks:
        eid = m.get("employeeId")
        if eid:
            if eid not in emp_raw_marks:
                emp_raw_marks[eid] = []
            emp_raw_marks[eid].append(m)

    events_to_send = []

    for rec in records:
        emp_id = rec.get("employeeExternalId") or rec.get("employeeId")
        if not emp_id:
            continue

        emp_name = rec.get("employeeName") or "—"
        dept_name = rec.get("departmentName") or rec.get("scheduleName") or "Без отдела"
        if mute_service.is_user_muted(emp_name) or mute_service.is_dept_muted(dept_name):
            continue

        date_str = rec.get("date", "")
        work_time_start_str = rec.get("workTimeStart")
        in_mark_str = rec.get("inMark")
        late_in = rec.get("lateIn") or 0

        plan_dt = _parse_dt(work_time_start_str)
        if not plan_dt:
            continue

        # Fallback to raw check-in marks if in_mark_str is missing in timetablespan
        if not in_mark_str:
            raw_ins = [m for m in emp_raw_marks.get(emp_id, []) if m.get("markType") == 0]
            if raw_ins:
                raw_ins.sort(key=lambda x: x.get("markDate", ""))
                in_mark_str = raw_ins[0].get("markDate")
                
                # Recalculate late_in minutes
                fact_in_dt = _parse_dt(in_mark_str)
                if fact_in_dt:
                    diff_mins = (fact_in_dt - plan_dt).total_seconds() / 60
                    late_in = max(0, int(diff_mins))

        # Logic: missing or late
        if not in_mark_str:
            # Not arrived yet
            passed_mins = (now_local - plan_dt).total_seconds() / 60
            if passed_mins >= 10:  # Threshold for missing
                event_key = _make_event_key(emp_id, date_str, "missing")
                if event_key not in sent_events_cache:
                    text = build_missing_message(rec, plan_dt, now_local)
                    events_to_send.append((event_key, text, emp_name, dept_name))
        else:
            # Arrived
            if late_in >= threshold:
                event_key = _make_event_key(emp_id, date_str, "late")
                if event_key not in sent_events_cache:
                    fact_dt = _parse_dt(in_mark_str)
                    if fact_dt:
                        text = build_late_message(rec, plan_dt, fact_dt, late_in)
                        events_to_send.append((event_key, text, emp_name, dept_name))

            # Early departure / Missing out mark
            out_mark_str = rec.get("outMark")
            plan_end_dt = _parse_dt(rec.get("workTimeEnd"))
            
            # Fallback to raw check-out marks if out_mark_str is missing in timetablespan
            early_out = rec.get("earlyOut") or 0
            if in_mark_str and plan_end_dt and not out_mark_str:
                raw_outs = [m for m in emp_raw_marks.get(emp_id, []) if m.get("markType") == 1]
                if raw_outs:
                    raw_outs.sort(key=lambda x: x.get("markDate", ""))
                    out_mark_str = raw_outs[-1].get("markDate")
                    
                    # Recalculate early_out minutes
                    fact_out_dt = _parse_dt(out_mark_str)
                    if fact_out_dt:
                        diff_out_mins = (plan_end_dt - fact_out_dt).total_seconds() / 60
                        early_out = max(0, int(diff_out_mins))
            
            if out_mark_str:
                if early_out >= threshold:
                    early_key = _make_event_key(emp_id, date_str, "early_out")
                    if early_key not in sent_events_cache:
                        fact_out_dt = _parse_dt(out_mark_str)
                        if plan_end_dt and fact_out_dt:
                            early_text = build_early_out_message(rec, plan_end_dt, fact_out_dt, early_out)
                            events_to_send.append((early_key, early_text, emp_name, dept_name))
            elif in_mark_str and plan_end_dt:
                passed_end_mins = (now_local - plan_end_dt).total_seconds() / 60
                if passed_end_mins >= 10:
                    missing_out_key = _make_event_key(emp_id, date_str, "missing_out")
                    if missing_out_key not in sent_events_cache:
                        missing_out_text = build_missing_out_message(rec, plan_end_dt, now_local)
                        events_to_send.append((missing_out_key, missing_out_text, emp_name, dept_name))

    for mark in marks:
        if mark.get("status") == 0:
            emp_id = mark.get("employeeId")
            mark_id = mark.get("id")
            if not emp_id or not mark_id:
                continue

            emp_name = mark.get("employeeName") or "—"
            dept_name = mark.get("departmentName") or "Без отдела"
            if mute_service.is_user_muted(emp_name) or mute_service.is_dept_muted(dept_name):
                continue
            mark_date_str = mark.get("markDate", "")[:10]
            event_key = _make_event_key(emp_id, mark_date_str, f"suspicious_{mark_id}")
            if event_key not in sent_events_cache:
                text = build_suspicious_mark_message(mark)
                events_to_send.append((event_key, text, emp_name, dept_name))

    for event_key, text, emp_name, dept_name in events_to_send:
        events_found += 1
        keyboard = {
            "inline_keyboard": [
                [{"text": "✅ Отбито", "callback_data": "review"}]
            ]
        }
        
        sent_to_any = False
        for chat_id in chats:
            if mute_service.is_event_muted_for_chat(chat_id, emp_name, dept_name):
                continue
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
