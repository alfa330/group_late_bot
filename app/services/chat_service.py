import json
import logging
import os
from typing import Optional

from app.config import settings
from app.services.department_service import normalize_text

logger = logging.getLogger(__name__)

CHATS_FILE = "chats.json"


class ChatService:
    def __init__(self):
        self.chats: dict[str, dict[str, Optional[str]]] = {}
        self._load()

    def _load(self):
        if os.path.exists(CHATS_FILE):
            try:
                with open(CHATS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.chats = {
                            str(chat_id): {"department_filter": None}
                            for chat_id in data
                        }
                        logger.info("Loaded %d chats from %s", len(self.chats), CHATS_FILE)
                    elif isinstance(data, dict):
                        chats_data = data.get("chats", data)
                        if isinstance(chats_data, dict):
                            self.chats = {
                                str(chat_id): {
                                    "department_filter": self._clean_department_filter(
                                        chat_settings.get("department_filter")
                                        or chat_settings.get("department")
                                    )
                                }
                                for chat_id, chat_settings in chats_data.items()
                                if isinstance(chat_settings, dict)
                            }
                            logger.info("Loaded %d chat profiles from %s", len(self.chats), CHATS_FILE)
            except Exception as e:
                logger.error("Failed to load %s: %s", CHATS_FILE, e)

        # Always ensure the default chat ID is included if we have one
        if settings.default_telegram_chat_id:
            self.chats.setdefault(settings.default_telegram_chat_id, {"department_filter": None})
            self._save()

    @staticmethod
    def _clean_department_filter(department_filter: Optional[str]) -> Optional[str]:
        value = str(department_filter or "").strip()
        return value or None

    def _save(self):
        try:
            with open(CHATS_FILE, "w", encoding="utf-8") as f:
                json.dump({"chats": self.chats}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save %s: %s", CHATS_FILE, e)

    def get_all_chats(self) -> list[str]:
        return list(self.chats.keys())

    def get_chat_settings(self, chat_id: str) -> dict[str, Optional[str]]:
        return self.chats.get(str(chat_id), {"department_filter": None})

    def add_chat(self, chat_id: str) -> bool:
        chat_id = str(chat_id)
        if chat_id in self.chats:
            return False
        self.chats[chat_id] = {"department_filter": None}
        self._save()
        logger.info("Added chat_id %s", chat_id)
        return True

    def remove_chat(self, chat_id: str) -> bool:
        chat_id = str(chat_id)
        if chat_id == settings.default_telegram_chat_id:
            # Prevent removing the default admin chat
            return False
        if chat_id in self.chats:
            del self.chats[chat_id]
            self._save()
            logger.info("Removed chat_id %s", chat_id)
            return True
        return False

    def set_chat_department(self, chat_id: str, department_name: str) -> bool:
        chat_id = str(chat_id)
        department_name = str(department_name or "").strip()
        if not department_name or chat_id not in self.chats:
            return False

        self.chats[chat_id]["department_filter"] = department_name
        self._save()
        logger.info("Set department filter for chat_id %s to %s", chat_id, department_name)
        return True

    def clear_chat_department(self, chat_id: str) -> bool:
        chat_id = str(chat_id)
        if chat_id not in self.chats:
            return False
        if not self.chats[chat_id].get("department_filter"):
            return False

        self.chats[chat_id]["department_filter"] = None
        self._save()
        logger.info("Cleared department filter for chat_id %s", chat_id)
        return True

    def get_chat_department(self, chat_id: str) -> Optional[str]:
        return self.get_chat_settings(chat_id).get("department_filter")

    def chat_allows_department(self, chat_id: str, department_name: str) -> bool:
        department_filter = self.get_chat_department(chat_id)
        if not department_filter:
            return True
        if not department_name:
            return False

        department_normalized = normalize_text(department_name)
        filter_normalized = normalize_text(department_filter)
        return filter_normalized in department_normalized or department_normalized in filter_normalized

    def format_chat_line(self, chat_id: str) -> str:
        department_filter = self.get_chat_department(chat_id)
        department_text = department_filter or "все отделы"
        return f"<code>{chat_id}</code> — {department_text}"


chat_service = ChatService()
