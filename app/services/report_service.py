import logging
import pytz
from datetime import datetime
from typing import Optional, Tuple
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

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

async def generate_report(date_str: str) -> Tuple[Optional[bytes], str, str]:
    """
    Generate a detailed Excel daily attendance report.
    Returns: (excel_bytes, filename, text_summary)
    """
    try:
        start_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None, "", "❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД (например, 2026-05-18)."

    start_local = start_date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    end_local = start_date.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=None)

    try:
        records = await workpace_client.get_all_timetable_spans(start_local, end_local)
        marks = await workpace_client.get_all_domain_marks(start_local, end_local)
    except Exception as exc:
        logger.error("Failed to fetch data for report: %s", exc)
        return None, "", f"❌ Ошибка получения данных от Workpace API:\n<code>{exc}</code>"

    threshold = settings.late_threshold_minutes

    # Correlate spans and marks by employeeId
    emp_data = {}

    for rec in records:
        if rec.get("employeeIsArchived") is True or str(rec.get("employeeIsArchived")).lower() == "true":
            continue
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
        if m.get("employeeIsArchived") is True or str(m.get("employeeIsArchived")).lower() == "true":
            continue
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
        return None, "", f"📊 <b>Отчет по посещаемости за {date_str}</b>\n\n📭 Данные отсутствуют."

    # Group by Department
    dept_groups = {}
    for emp_id, info in emp_data.items():
        info["marks"].sort(key=lambda x: x.get("markDate", ""))
        dept = info["dept"]
        if dept not in dept_groups:
            dept_groups[dept] = []
        dept_groups[dept].append(info)

    # Initialize openpyxl Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Посещаемость"

    # Style Definitions (Premium Blues & Compliance Colors)
    font_title = Font(name="Arial", size=14, bold=True, color="1F4E78")
    font_header = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    font_bold = Font(name="Arial", size=9, bold=True)
    font_regular = Font(name="Arial", size=9)
    
    fill_header = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    fill_even = PatternFill(start_color="F2F5F8", end_color="F2F5F8", fill_type="solid")
    fill_odd = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    
    fill_green = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")  # light green
    fill_red = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")    # light red
    fill_yellow = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid") # light yellow

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")

    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9")
    )

    # Title block
    ws.append([f"Отчет по посещаемости за {date_str}"])
    ws.cell(row=1, column=1).font = font_title
    ws.row_dimensions[1].height = 30
    ws.append([]) # Spacer

    # Headers
    headers = [
        "Отдел", "ФИО сотрудника", "График", "Все отметки за день",
        "Время прихода (план)", "Время прихода (факт)", "Опоздание (мин)",
        "Время ухода (план)", "Время ухода (факт)", "Ранний уход (мин)",
        "Отработано (факт)", "Отклонение (HH:MM)", "Статус"
    ]
    ws.append(headers)
    ws.row_dimensions[3].height = 25

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=3, column=col_idx)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = thin_border

    # Calculate statistics & Fill rows
    total_employees = len(emp_data)
    ontime_count = 0
    late_count = 0
    absent_count = 0
    early_out_count = 0
    suspicious_marks_count = 0

    for m in marks:
        if m.get("status") == 0:
            suspicious_marks_count += 1

    current_row = 4
    for dept_name, emps in sorted(dept_groups.items()):
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

            plan_in = "—"
            fact_in = "—"
            late_in = 0
            plan_out = "—"
            fact_out = "—"
            early_out = 0
            status_text = "Вне графика"
            status_fill = fill_yellow
            
            fact_in_dt = None
            fact_out_dt = None

            if span:
                plan_in_dt = _parse_dt(span.get("workTimeStart"))
                fact_in_dt = _parse_dt(span.get("inMark"))
                
                # Fallback to earliest raw check-in if fact_in_dt is missing but we have raw check-in marks
                if not fact_in_dt and plan_in_dt:
                    in_marks = [m for m in raw_marks if m.get("markType") == 0]
                    if in_marks:
                        fact_in_dt = _parse_dt(in_marks[0].get("markDate"))

                plan_in = plan_in_dt.strftime("%H:%M") if plan_in_dt else "—"
                fact_in = fact_in_dt.strftime("%H:%M") if fact_in_dt else "—"
                
                if plan_in_dt and fact_in_dt:
                    diff_mins = (fact_in_dt - plan_in_dt).total_seconds() / 60
                    late_in = max(0, int(diff_mins))
                else:
                    late_in = span.get("lateIn") or 0

                plan_out_dt = _parse_dt(span.get("workTimeEnd"))
                fact_out_dt = _parse_dt(span.get("outMark"))
                
                # Fallback to latest raw check-out if fact_out_dt is missing but we have raw check-out marks
                if not fact_out_dt and plan_out_dt:
                    out_marks = [m for m in raw_marks if m.get("markType") == 1]
                    if out_marks:
                        fact_out_dt = _parse_dt(out_marks[-1].get("markDate"))

                plan_out = plan_out_dt.strftime("%H:%M") if plan_out_dt else "—"
                fact_out = fact_out_dt.strftime("%H:%M") if fact_out_dt else "—"

                if plan_out_dt and fact_out_dt:
                    diff_out_mins = (plan_out_dt - fact_out_dt).total_seconds() / 60
                    early_out = max(0, int(diff_out_mins))
                else:
                    early_out = span.get("earlyOut") or 0

                if not fact_in_dt:
                    status_text = "Отсутствует"
                    status_fill = fill_red
                    absent_count += 1
                else:
                    status_parts = []
                    if late_in >= threshold:
                        status_parts.append(f"Опоздал ({late_in} м)")
                        status_fill = fill_red
                        late_count += 1
                    if early_out >= threshold:
                        status_parts.append(f"Ранний уход ({early_out} м)")
                        status_fill = fill_red
                        early_out_count += 1
                    
                    # Highlight if the first check-in mark is suspicious
                    in_marks = [m for m in raw_marks if m.get("markType") == 0]
                    is_susp = in_marks and in_marks[0].get("status") == 0
                    
                    if not status_parts:
                        if is_susp:
                            status_parts.append("Вовремя (⚠️)")
                            status_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid") # light warning yellow
                        else:
                            status_parts.append("Вовремя")
                            status_fill = fill_green
                        ontime_count += 1
                    else:
                        if is_susp:
                            status_parts.append("(⚠️)")
                        status_fill = fill_red
                    status_text = ", ".join(status_parts)
            else:
                # No schedule
                if raw_marks:
                    in_marks = [m for m in raw_marks if m.get("markType") == 0]
                    if in_marks:
                        fact_in_dt = _parse_dt(in_marks[0].get("markDate"))
                        fact_in = fact_in_dt.strftime("%H:%M") if fact_in_dt else "—"

                    out_marks = [m for m in raw_marks if m.get("markType") == 1]
                    if out_marks:
                        fact_out_dt = _parse_dt(out_marks[-1].get("markDate"))
                        fact_out = fact_out_dt.strftime("%H:%M") if fact_out_dt else "—"

                    status_text = "Вне графика"
                    status_fill = fill_yellow
                else:
                    status_text = "Не явился"
                    status_fill = fill_red
                    absent_count += 1

            # Calculate worked hours (HH:MM) from earliest in and latest out
            work_time_str = "—"
            if fact_in_dt and fact_out_dt:
                diff_sec = (fact_out_dt - fact_in_dt).total_seconds()
                if diff_sec > 0:
                    h = int(diff_sec // 3600)
                    m = int((diff_sec % 3600) // 60)
                    work_time_str = f"{h:02d}:{m:02d}"

            # Calculate work deviation (HH:MM) from planned norm
            deviation_str = "—"
            if span and fact_in_dt and fact_out_dt:
                plan_in_dt = _parse_dt(span.get("workTimeStart"))
                plan_out_dt = _parse_dt(span.get("workTimeEnd"))
                if plan_in_dt and plan_out_dt:
                    norm_sec = (plan_out_dt - plan_in_dt).total_seconds()
                    fact_sec = (fact_out_dt - fact_in_dt).total_seconds()
                    if norm_sec > 0:
                        diff_sec = fact_sec - norm_sec
                        sign = "+" if diff_sec >= 0 else "-"
                        abs_diff = abs(diff_sec)
                        h = int(abs_diff // 3600)
                        m = int((abs_diff % 3600) // 60)
                        deviation_str = f"{sign}{h:02d}:{m:02d}"

            row_data = [
                dept_name, name, info.get("span", {}).get("scheduleName", "—") if info.get("span") else "—",
                marks_str, plan_in, fact_in, late_in if late_in > 0 else "—",
                plan_out, fact_out, early_out if early_out > 0 else "—",
                work_time_str, deviation_str, status_text
            ]
            ws.append(row_data)
            ws.row_dimensions[current_row].height = 20

            # Stylize the row cells
            for col_idx in range(1, 14):
                cell = ws.cell(row=current_row, column=col_idx)
                cell.font = font_regular
                cell.border = thin_border
                
                # Alignments
                if col_idx in [1, 2, 3, 4]:
                    cell.alignment = align_left
                else:
                    cell.alignment = align_center
                
                # Apply special fill to status column
                if col_idx == 13:
                    cell.fill = status_fill
                    cell.font = font_bold
                else:
                    # Zebra striping for rows
                    if current_row % 2 == 0:
                        cell.fill = fill_even
                    else:
                        cell.fill = fill_odd

            current_row += 1

    # Auto-fit column widths
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            val = str(cell.value or "")
            if cell.row == 1:
                continue # Skip title length
            # Account for ⚠️ prefix spacing
            if len(val) > max_len:
                max_len = len(val)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 10)

    # Save to memory buffer
    file_stream = BytesIO()
    wb.save(file_stream)
    excel_bytes = file_stream.getvalue()
    
    filename = f"Attendance_Report_{date_str}.xlsx"

    # Polish summary caption
    summary_lines = [
        f"📊 <b>Отчет по посещаемости за {date_str}</b>\n",
        "📈 <b>Итоги дня по всей компании:</b>",
        f"• Всего сотрудников: <b>{total_employees}</b>",
        f"• Пришли вовремя: <b>{ontime_count}</b>",
        f"• Опоздали: <b>{late_count}</b>",
        f"• Отсутствуют: <b>{absent_count}</b>",
    ]
    if early_out_count > 0:
        summary_lines.append(f"• Ранний уход: <b>{early_out_count}</b>")
    if suspicious_marks_count > 0:
        summary_lines.append(f"• Подозрительные отметки: <b>⚠️ {suspicious_marks_count}</b>")
    
    summary_lines.append("\n📂 <i>Детальный отчет с разбивкой по отделам и всеми отметками прикреплен в Excel-файле ниже.</i>")

    return excel_bytes, filename, "\n".join(summary_lines)
