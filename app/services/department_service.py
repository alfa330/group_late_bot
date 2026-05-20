from typing import Iterable, Optional

from app.workpace_client import workpace_client

NO_DEPARTMENT = "Без отдела"


def _clean(value) -> str:
    return str(value or "").strip()


def normalize_text(value: str) -> str:
    return _clean(value).casefold()


def employee_full_name(employee: dict) -> str:
    name_value = employee.get("name")
    direct_name = _clean(
        employee.get("fullName")
        or employee.get("employeeName")
        or (name_value if not isinstance(name_value, dict) else "")
    )
    if direct_name:
        return direct_name

    name_obj = name_value if isinstance(name_value, dict) else {}
    parts = [
        _clean(employee.get("lastName") or name_obj.get("lastName")),
        _clean(employee.get("firstName") or name_obj.get("firstName")),
        _clean(employee.get("middleName") or name_obj.get("middleName")),
    ]
    return " ".join(part for part in parts if part)


def department_name_from_fields(item: dict) -> Optional[str]:
    for field in ("departmentName", "department"):
        value = _clean(item.get(field))
        if value:
            return value

    department_tree = _clean(item.get("departmentTree"))
    if department_tree:
        separators = (" / ", "/", "\\", ">", "»")
        for separator in separators:
            if separator in department_tree:
                parts = [part.strip() for part in department_tree.split(separator) if part.strip()]
                if parts:
                    return parts[-1]
        return department_tree

    return None


def build_employee_department_lookup(employees: Iterable[dict]) -> dict[str, dict[str, str]]:
    lookup = {
        "by_id": {},
        "by_external_id": {},
        "by_name": {},
    }

    for employee in employees:
        department_name = department_name_from_fields(employee)
        if not department_name:
            continue

        employee_id = _clean(employee.get("id") or employee.get("employeeId"))
        if employee_id:
            lookup["by_id"][employee_id] = department_name

        external_id = _clean(employee.get("externalId") or employee.get("employeeExternalId"))
        if external_id:
            lookup["by_external_id"][external_id] = department_name

        full_name = employee_full_name(employee)
        if full_name:
            lookup["by_name"][normalize_text(full_name)] = department_name

    return lookup


def resolve_department_name(item: dict, employee_lookup: dict[str, dict[str, str]]) -> str:
    employee_id = _clean(item.get("employeeId") or item.get("id"))
    if employee_id and employee_id in employee_lookup.get("by_id", {}):
        return employee_lookup["by_id"][employee_id]

    external_id = _clean(item.get("employeeExternalId") or item.get("externalId"))
    if external_id and external_id in employee_lookup.get("by_external_id", {}):
        return employee_lookup["by_external_id"][external_id]

    name_value = item.get("name")
    employee_name = _clean(
        item.get("employeeName")
        or item.get("fullName")
        or (name_value if not isinstance(name_value, dict) else "")
    )
    if employee_name:
        by_name = employee_lookup.get("by_name", {})
        normalized_name = normalize_text(employee_name)
        if normalized_name in by_name:
            return by_name[normalized_name]

    return department_name_from_fields(item) or NO_DEPARTMENT


async def get_employee_department_lookup(active_only: bool = True) -> dict[str, dict[str, str]]:
    employees = await workpace_client.get_all_employees(active_only=active_only)
    return build_employee_department_lookup(employees)


async def get_department_names(active_only: bool = True) -> list[str]:
    employees = await workpace_client.get_all_employees(active_only=active_only)
    departments = {
        department_name_from_fields(employee)
        for employee in employees
        if department_name_from_fields(employee)
    }
    return sorted(departments, key=normalize_text)
