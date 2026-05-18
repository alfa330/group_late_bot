import json
import logging
import os
from typing import Set

from app.config import settings

logger = logging.getLogger(__name__)

CHATS_FILE = "chats.json"


class ChatService:
    def __init__(self):
        self.chats: Set[str] = set()
        self._load()

    def _load(self):
        if os.path.exists(CHATS_FILE):
            try:
                with open(CHATS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.chats = set(data)
                        logger.info("Loaded %d chats from %s", len(self.chats), CHATS_FILE)
            except Exception as e:
                logger.error("Failed to load %s: %s", CHATS_FILE, e)

        # Always ensure the default chat ID is included if we have one
        if settings.default_telegram_chat_id:
            self.chats.add(settings.default_telegram_chat_id)
            self._save()

    def _save(self):
        try:
            with open(CHATS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self.chats), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save %s: %s", CHATS_FILE, e)

    def get_all_chats(self) -> list[str]:
        return list(self.chats)

    def add_chat(self, chat_id: str) -> bool:
        if chat_id in self.chats:
            return False
        self.chats.add(chat_id)
        self._save()
        logger.info("Added chat_id %s", chat_id)
        return True

    def remove_chat(self, chat_id: str) -> bool:
        if chat_id == settings.default_telegram_chat_id:
            # Prevent removing the default admin chat
            return False
        if chat_id in self.chats:
            self.chats.remove(chat_id)
            self._save()
            logger.info("Removed chat_id %s", chat_id)
            return True
        return False


chat_service = ChatService()
