import json
import logging
import os
import re
from typing import Optional

from app.config import settings
from app.services.department_service import normalize_text

logger = logging.getLogger(__name__)

CHATS_FILE = "chats.json"


class ChatService:
    def __init__(self):
        self.chats: dict[str, dict[str, list[str]]] = {}
        self._load()

    def _load(self):
        if os.path.exists(CHATS_FILE):
            try:
                with open(CHATS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.chats = {
                            str(chat_id): {"department_filters": []}
                            for chat_id in data
                        }
                        logger.info("Loaded %d chats from %s", len(self.chats), CHATS_FILE)
                    elif isinstance(data, dict):
                        chats_data = data.get("chats", data)
                        if isinstance(chats_data, dict):
                            self.chats = {
                                str(chat_id): {
                                    "department_filters": self._clean_department_filters(
                                        chat_settings.get("department_filters")
                                        or chat_settings.get("department_filter")
                                        or chat_settings.get("department")
                                    )
                                }
                                for chat_id, chat_settings in chats_data.items()
                                if isinstance(chat_settings, dict)
                            }
                            logger.info("Loaded %d chat profiles from %s", len(self.chats), CHATS_FILE)
            except Exception as e:
                logger.error("Failed to load %s: %s", CHATS_FILE, e)

        # Always ensure the admin chat IDs are included
        for admin_id in settings.admin_ids:
            self.chats.setdefault(admin_id, {"department_filters": []})
        if settings.admin_ids:
            self._save()

    @staticmethod
    def _clean_department_filters(department_filters) -> list[str]:
        if department_filters is None:
            return []

        raw_values = department_filters
        if isinstance(raw_values, str):
            raw_values = re.split(r"\s*[;|]\s*", raw_values)
        elif not isinstance(raw_values, list):
            raw_values = [raw_values]

        clean_values = []
        seen = set()
        for raw_value in raw_values:
            value = str(raw_value or "").strip()
            if not value:
                continue
            normalized = normalize_text(value)
            if normalized in seen:
                continue
            seen.add(normalized)
            clean_values.append(value)
        return clean_values

    def _save(self):
        try:
            with open(CHATS_FILE, "w", encoding="utf-8") as f:
                json.dump({"chats": self.chats}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save %s: %s", CHATS_FILE, e)

    def get_all_chats(self) -> list[str]:
        return list(self.chats.keys())

    def get_chat_settings(self, chat_id: str) -> dict[str, list[str]]:
        return self.chats.get(str(chat_id), {"department_filters": []})

    def add_chat(self, chat_id: str) -> bool:
        chat_id = str(chat_id)
        if chat_id in self.chats:
            return False
        self.chats[chat_id] = {"department_filters": []}
        self._save()
        logger.info("Added chat_id %s", chat_id)
        return True

    def remove_chat(self, chat_id: str) -> bool:
        chat_id = str(chat_id)
        if chat_id in settings.admin_ids:
            # Prevent removing the admin chats
            return False
        if chat_id in self.chats:
            del self.chats[chat_id]
            self._save()
            logger.info("Removed chat_id %s", chat_id)
            return True
        return False

    def set_chat_department(self, chat_id: str, department_name: str) -> bool:
        chat_id = str(chat_id)
        department_filters = self._clean_department_filters(department_name)
        if not department_filters or chat_id not in self.chats:
            return False

        self.chats[chat_id]["department_filters"] = department_filters
        self._save()
        logger.info("Set department filters for chat_id %s to %s", chat_id, department_filters)
        return True

    def add_chat_department(self, chat_id: str, department_name: str) -> bool:
        chat_id = str(chat_id)
        new_filters = self._clean_department_filters(department_name)
        if not new_filters or chat_id not in self.chats:
            return False

        current_filters = self.get_chat_departments(chat_id)
        seen = {normalize_text(value) for value in current_filters}
        changed = False
        for department_filter in new_filters:
            normalized = normalize_text(department_filter)
            if normalized in seen:
                continue
            current_filters.append(department_filter)
            seen.add(normalized)
            changed = True

        if not changed:
            return False

        self.chats[chat_id]["department_filters"] = current_filters
        self._save()
        logger.info("Added department filters for chat_id %s: %s", chat_id, new_filters)
        return True

    def remove_chat_department(self, chat_id: str, department_name: str) -> bool:
        chat_id = str(chat_id)
        department_name = str(department_name or "").strip()
        if not department_name or chat_id not in self.chats:
            return False

        normalized = normalize_text(department_name)
        current_filters = self.get_chat_departments(chat_id)
        remaining_filters = [
            value
            for value in current_filters
            if normalized not in normalize_text(value)
            and normalize_text(value) not in normalized
        ]
        if len(remaining_filters) == len(current_filters):
            return False

        self.chats[chat_id]["department_filters"] = remaining_filters
        self._save()
        logger.info("Removed department filter for chat_id %s: %s", chat_id, department_name)
        return True

    def clear_chat_department(self, chat_id: str) -> bool:
        chat_id = str(chat_id)
        if chat_id not in self.chats:
            return False
        if not self.chats[chat_id].get("department_filters"):
            return False

        self.chats[chat_id]["department_filters"] = []
        self._save()
        logger.info("Cleared department filters for chat_id %s", chat_id)
        return True

    def get_chat_departments(self, chat_id: str) -> list[str]:
        settings = self.get_chat_settings(chat_id)
        return list(settings.get("department_filters") or [])

    def get_chat_department(self, chat_id: str) -> Optional[str]:
        departments = self.get_chat_departments(chat_id)
        return departments[0] if departments else None

    def chat_allows_department(self, chat_id: str, department_name: str) -> bool:
        department_filters = self.get_chat_departments(chat_id)
        if not department_filters:
            return True
        if not department_name:
            return False

        department_normalized = normalize_text(department_name)
        return any(
            filter_normalized in department_normalized
            or department_normalized in filter_normalized
            for filter_normalized in (normalize_text(value) for value in department_filters)
        )

    def format_chat_line(self, chat_id: str) -> str:
        department_filters = self.get_chat_departments(chat_id)
        department_text = ", ".join(department_filters) if department_filters else "все отделы"
        return f"<code>{chat_id}</code> — {department_text}"


chat_service = ChatService()
