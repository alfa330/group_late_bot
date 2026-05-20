import json
import logging
import os
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

MUTES_FILE = "mutes.json"


class MuteService:
    def __init__(self):
        self.all_muted: bool = False
        self.muted_users: Set[str] = set()
        self.muted_depts: Set[str] = set()
        self.chat_mutes: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if os.path.exists(MUTES_FILE):
            try:
                with open(MUTES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.all_muted = bool(data.get("all_muted", False))
                        self.muted_users = set(data.get("muted_users", []))
                        self.muted_depts = set(data.get("muted_depts", []))
                        chat_mutes = data.get("chat_mutes", {})
                        if isinstance(chat_mutes, dict):
                            self.chat_mutes = {
                                str(chat_id): {
                                    "all_muted": bool(settings.get("all_muted", False)),
                                    "muted_users": set(settings.get("muted_users", [])),
                                    "muted_depts": set(settings.get("muted_depts", [])),
                                }
                                for chat_id, settings in chat_mutes.items()
                                if isinstance(settings, dict)
                            }
                        logger.info(
                            "Loaded %d global muted users, %d global muted departments and %d chat mute profiles from %s",
                            len(self.muted_users),
                            len(self.muted_depts),
                            len(self.chat_mutes),
                            MUTES_FILE,
                        )
            except Exception as e:
                logger.error("Failed to load %s: %s", MUTES_FILE, e)

    def _save(self):
        try:
            with open(MUTES_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "all_muted": self.all_muted,
                    "muted_users": sorted(self.muted_users),
                    "muted_depts": sorted(self.muted_depts),
                    "chat_mutes": {
                        chat_id: {
                            "all_muted": bool(settings.get("all_muted", False)),
                            "muted_users": sorted(settings["muted_users"]),
                            "muted_depts": sorted(settings["muted_depts"]),
                        }
                        for chat_id, settings in sorted(self.chat_mutes.items())
                    },
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save %s: %s", MUTES_FILE, e)

    def _get_chat_settings(self, chat_id: str) -> dict:
        chat_id = str(chat_id)
        if chat_id not in self.chat_mutes:
            self.chat_mutes[chat_id] = {
                "all_muted": False,
                "muted_users": set(),
                "muted_depts": set(),
            }
        return self.chat_mutes[chat_id]

    def _cleanup_chat_settings(self, chat_id: str):
        settings = self.chat_mutes.get(str(chat_id))
        if (
            settings
            and not settings.get("all_muted", False)
            and not settings["muted_users"]
            and not settings["muted_depts"]
        ):
            del self.chat_mutes[str(chat_id)]

    @staticmethod
    def _is_match(value: str, muted_values: Set[str]) -> bool:
        if not value:
            return False
        value_lower = value.strip().lower()
        return any(muted.lower() in value_lower for muted in muted_values)

    def mute_user(self, user_name: str, chat_id: Optional[str] = None) -> bool:
        user_name_stripped = user_name.strip()
        if not user_name_stripped:
            return False
        target = self._get_chat_settings(chat_id)["muted_users"] if chat_id else self.muted_users
        if user_name_stripped in target:
            return False
        target.add(user_name_stripped)
        self._save()
        logger.info("Muted user %s for chat %s", user_name_stripped, chat_id or "global")
        return True

    def unmute_user(self, user_name: str, chat_id: Optional[str] = None) -> bool:
        user_name_stripped = user_name.strip()
        if not user_name_stripped:
            return False

        if chat_id:
            settings = self.chat_mutes.get(str(chat_id))
            if not settings:
                return False
            target = settings["muted_users"]
        else:
            target = self.muted_users

        # Check for exact match first
        if user_name_stripped in target:
            target.remove(user_name_stripped)
            if chat_id:
                self._cleanup_chat_settings(chat_id)
            self._save()
            logger.info("Unmuted user %s for chat %s", user_name_stripped, chat_id or "global")
            return True

        # Try case-insensitive matching
        for u in list(target):
            if u.lower() == user_name_stripped.lower():
                target.remove(u)
                if chat_id:
                    self._cleanup_chat_settings(chat_id)
                self._save()
                logger.info("Unmuted user %s for chat %s", u, chat_id or "global")
                return True

        return False

    def mute_dept(self, dept_name: str, chat_id: Optional[str] = None) -> bool:
        dept_name_stripped = dept_name.strip()
        if not dept_name_stripped:
            return False
        target = self._get_chat_settings(chat_id)["muted_depts"] if chat_id else self.muted_depts
        if dept_name_stripped in target:
            return False
        target.add(dept_name_stripped)
        self._save()
        logger.info("Muted department %s for chat %s", dept_name_stripped, chat_id or "global")
        return True

    def mute_all(self, chat_id: Optional[str] = None) -> bool:
        if chat_id:
            settings = self._get_chat_settings(chat_id)
            if settings.get("all_muted", False):
                return False
            settings["all_muted"] = True
        else:
            if self.all_muted:
                return False
            self.all_muted = True

        self._save()
        logger.info("Muted all notifications for chat %s", chat_id or "global")
        return True

    def unmute_all(self, chat_id: Optional[str] = None) -> bool:
        if chat_id:
            settings = self.chat_mutes.get(str(chat_id))
            if not settings or not settings.get("all_muted", False):
                return False
            settings["all_muted"] = False
            self._cleanup_chat_settings(chat_id)
        else:
            if not self.all_muted:
                return False
            self.all_muted = False

        self._save()
        logger.info("Unmuted all notifications for chat %s", chat_id or "global")
        return True

    def unmute_dept(self, dept_name: str, chat_id: Optional[str] = None) -> bool:
        dept_name_stripped = dept_name.strip()
        if not dept_name_stripped:
            return False

        if chat_id:
            settings = self.chat_mutes.get(str(chat_id))
            if not settings:
                return False
            target = settings["muted_depts"]
        else:
            target = self.muted_depts

        # Check for exact match first
        if dept_name_stripped in target:
            target.remove(dept_name_stripped)
            if chat_id:
                self._cleanup_chat_settings(chat_id)
            self._save()
            logger.info("Unmuted department %s for chat %s", dept_name_stripped, chat_id or "global")
            return True

        # Try case-insensitive matching
        for d in list(target):
            if d.lower() == dept_name_stripped.lower():
                target.remove(d)
                if chat_id:
                    self._cleanup_chat_settings(chat_id)
                self._save()
                logger.info("Unmuted department %s for chat %s", d, chat_id or "global")
                return True

        return False

    def is_user_muted(self, user_name: str, chat_id: Optional[str] = None) -> bool:
        if self._is_match(user_name, self.muted_users):
            return True
        if chat_id:
            settings = self.chat_mutes.get(str(chat_id))
            return bool(settings and self._is_match(user_name, settings["muted_users"]))
        return False

    def is_dept_muted(self, dept_name: str, chat_id: Optional[str] = None) -> bool:
        if self._is_match(dept_name, self.muted_depts):
            return True
        if chat_id:
            settings = self.chat_mutes.get(str(chat_id))
            return bool(settings and self._is_match(dept_name, settings["muted_depts"]))
        return False

    def is_all_muted(self, chat_id: Optional[str] = None) -> bool:
        if self.all_muted:
            return True
        if chat_id:
            settings = self.chat_mutes.get(str(chat_id))
            return bool(settings and settings.get("all_muted", False))
        return False

    def is_event_muted_for_chat(self, chat_id: str, user_name: str, dept_name: str) -> bool:
        return (
            self.is_all_muted(chat_id)
            or self.is_user_muted(user_name, chat_id)
            or self.is_dept_muted(dept_name, chat_id)
        )

    def get_muted_users(self, chat_id: Optional[str] = None) -> list[str]:
        if chat_id:
            return sorted(self.chat_mutes.get(str(chat_id), {}).get("muted_users", set()))
        return sorted(self.muted_users)

    def get_muted_depts(self, chat_id: Optional[str] = None) -> list[str]:
        if chat_id:
            return sorted(self.chat_mutes.get(str(chat_id), {}).get("muted_depts", set()))
        return sorted(self.muted_depts)

    def get_all_muted(self, chat_id: Optional[str] = None) -> bool:
        if chat_id:
            return bool(self.chat_mutes.get(str(chat_id), {}).get("all_muted", False))
        return self.all_muted


mute_service = MuteService()
