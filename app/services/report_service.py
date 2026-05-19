import logging
import pytz
from datetime import datetime
from typing import Optional

from app.config import settings
from app.workpace_client import workpace_client

logger = logging.getLogger(__name__)
TZ = pytz.timezone(settings.timezone)

def _parse_dt(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ):
        try:
            dt = datetime.strptime(dt_str, fmt)
            if dt.tzinfo is not None:
                return dt.astimezone(TZ)
            elif dt_str.endswith("Z"):
                dt = pytz.utc.localize(dt)
                return dt.astimezone(TZ)
            else:
                return TZ.localize(dt)
        except ValueError:
            continue
    return None

async def generate_report(date_str: str) -> str:
    """Generate a beautiful, formatted daily attendance report for the given date."""
    try:
        start_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return "❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД (например, 2026-05-18)."

    start_local = start_date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    end_local = start_date.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)

    try:
        records = await workpace_client.get_all_timetable_spans(start_local, end_local)
        marks = await workpace_client.get_all_domain_marks(start_local, end_local)
    except Exception as exc:
        logger.error("Failed to fetch data for report: %s", exc)
        return f"❌ Ошибка получения данных от Workpace API:\n<code>{exc}</code>"

    threshold = settings.late_threshold_minutes

    # Correlate spans and marks by employeeId
    # emp_id -> { "span": rec, "marks": [], "name": ... }
    emp_data = {}

    for rec in records:
        emp_id = rec.get("employeeExternalId") or rec.get("employeeId")
        if not emp_id:
            continue
        emp_name = rec.get("employeeName") or "—"
        if emp_id not in emp_data:
            emp_data[emp_id] = {
                "span": rec,
                "marks": [],
                "name": emp_name,
                "dept": rec.get("departmentName") or rec.get("scheduleName") or "Без отдела"
            }
        else:
            emp_data[emp_id]["span"] = rec
            if rec.get("departmentName"):
                emp_data[emp_id]["dept"] = rec["departmentName"]

    for m in marks:
        emp_id = m.get("employeeId")
        if not emp_id:
            continue
        emp_name = m.get("employeeName") or "—"
        if emp_id not in emp_data:
            emp_data[emp_id] = {
                "span": None,
                "marks": [m],
                "name": emp_name,
                "dept": m.get("departmentName") or "Без отдела"
            }
        else:
            emp_data[emp_id]["marks"].append(m)

    if not emp_data:
        return f"📊 <b>Отчет по посещаемости за {date_str}</b>\n\n📭 Данные отсутствуют."

    # Group by Department
    dept_groups = {} # dept_name -> list of emp_info
    for emp_id, info in emp_data.items():
        # Sort marks chronologically
        info["marks"].sort(key=lambda x: x.get("markDate", ""))
        dept = info["dept"]
        if dept not in dept_groups:
            dept_groups[dept] = []
        dept_groups[dept].append(info)

    # Calculate statistics
    total_employees = len(emp_data)
    ontime_count = 0
    late_count = 0
    absent_count = 0
    early_out_count = 0
    suspicious_marks_count = 0

    for m in marks:
        if m.get("status") == 0:
            suspicious_marks_count += 1

    report_lines = [f"📊 <b>Отчет по посещаемости за {date_str}</b>\n"]

    # Build report text
    for dept_name, emps in sorted(dept_groups.items()):
        report_lines.append(f"🏢 <b>{dept_name}</b>")
        
        # Sort employees alphabetically
        for info in sorted(emps, key=lambda x: x["name"]):
            name = info["name"]
            span = info["span"]
            raw_marks = info["marks"]

            # Format raw marks list
            formatted_marks = []
            for m in raw_marks:
                m_dt = _parse_dt(m.get("markDate"))
                m_time = m_dt.strftime("%H:%M") if m_dt else "??:??"
                
                mtype_val = m.get("markType")
                mtype = "Вход" if mtype_val == 0 else "Выход" if mtype_val == 1 else "Отм"
                
                is_suspicious = m.get("status") == 0
                susp_prefix = "⚠️ " if is_suspicious else ""
                formatted_marks.append(f"{susp_prefix}{m_time}({mtype})")

            marks_str = ", ".join(formatted_marks) if formatted_marks else "нет отметок"

            # Parse compliance badges
            badges = []
            if span:
                in_mark = span.get("inMark")
                late_in = span.get("lateIn") or 0
                early_out = span.get("earlyOut") or 0
                
                if not in_mark:
                    badges.append("🚨 Отсутствует")
                    absent_count += 1
                else:
                    if late_in >= threshold:
                        badges.append(f"⏰ Опоздал ({late_in} мин)")
                        late_count += 1
                    else:
                        badges.append("✅ Вовремя")
                        ontime_count += 1
                        
                    if early_out >= threshold:
                        badges.append(f"🏃 Ранний уход ({early_out} мин)")
                        early_out_count += 1
            else:
                badges.append("ℹ️ Вне графика")

            badges_str = f" [<i>{', '.join(badges)}</i>]" if badges else ""
            report_lines.append(f"• <b>{name}</b>: {marks_str}{badges_str}")
        report_lines.append("") # Spacer between depts

    # Company Summary
    report_lines.append("📈 <b>Итоги дня по всей компании:</b>")
    report_lines.append(f"• Всего сотрудников: <b>{total_employees}</b>")
    report_lines.append(f"• Пришли вовремя: <b>{ontime_count}</b>")
    report_lines.append(f"• Опоздали: <b>{late_count}</b>")
    report_lines.append(f"• Отсутствуют: <b>{absent_count}</b>")
    if early_out_count > 0:
        report_lines.append(f"• Ранний уход: <b>{early_out_count}</b>")
    if suspicious_marks_count > 0:
        report_lines.append(f"• Подозрительные отметки: <b>⚠️ {suspicious_marks_count}</b>")

    return "\n".join(report_lines)
