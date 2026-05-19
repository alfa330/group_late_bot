import json
import logging
import os
from typing import Set

logger = logging.getLogger(__name__)

MUTES_FILE = "mutes.json"


class MuteService:
    def __init__(self):
        self.muted_users: Set[str] = set()
        self.muted_depts: Set[str] = set()
        self._load()

    def _load(self):
        if os.path.exists(MUTES_FILE):
            try:
                with open(MUTES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.muted_users = set(data.get("muted_users", []))
                        self.muted_depts = set(data.get("muted_depts", []))
                        logger.info("Loaded %d muted users and %d muted departments from %s", 
                                    len(self.muted_users), len(self.muted_depts), MUTES_FILE)
            except Exception as e:
                logger.error("Failed to load %s: %s", MUTES_FILE, e)

    def _save(self):
        try:
            with open(MUTES_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "muted_users": list(self.muted_users),
                    "muted_depts": list(self.muted_depts)
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save %s: %s", MUTES_FILE, e)

    def mute_user(self, user_name: str) -> bool:
        user_name_stripped = user_name.strip()
        if not user_name_stripped:
            return False
        if user_name_stripped in self.muted_users:
            return False
        self.muted_users.add(user_name_stripped)
        self._save()
        logger.info("Muted user: %s", user_name_stripped)
        return True

    def unmute_user(self, user_name: str) -> bool:
        user_name_stripped = user_name.strip()
        if not user_name_stripped:
            return False
        
        # Check for exact match first
        if user_name_stripped in self.muted_users:
            self.muted_users.remove(user_name_stripped)
            self._save()
            logger.info("Unmuted user: %s", user_name_stripped)
            return True
            
        # Try case-insensitive matching
        for u in list(self.muted_users):
            if u.lower() == user_name_stripped.lower():
                self.muted_users.remove(u)
                self._save()
                logger.info("Unmuted user: %s", u)
                return True
                
        return False

    def mute_dept(self, dept_name: str) -> bool:
        dept_name_stripped = dept_name.strip()
        if not dept_name_stripped:
            return False
        if dept_name_stripped in self.muted_depts:
            return False
        self.muted_depts.add(dept_name_stripped)
        self._save()
        logger.info("Muted department: %s", dept_name_stripped)
        return True

    def unmute_dept(self, dept_name: str) -> bool:
        dept_name_stripped = dept_name.strip()
        if not dept_name_stripped:
            return False
            
        # Check for exact match first
        if dept_name_stripped in self.muted_depts:
            self.muted_depts.remove(dept_name_stripped)
            self._save()
            logger.info("Unmuted department: %s", dept_name_stripped)
            return True
            
        # Try case-insensitive matching
        for d in list(self.muted_depts):
            if d.lower() == dept_name_stripped.lower():
                self.muted_depts.remove(d)
                self._save()
                logger.info("Unmuted department: %s", d)
                return True
                
        return False

    def is_user_muted(self, user_name: str) -> bool:
        if not user_name:
            return False
        user_name_lower = user_name.strip().lower()
        for mu in self.muted_users:
            mu_lower = mu.lower()
            if mu_lower in user_name_lower:
                return True
        return False

    def is_dept_muted(self, dept_name: str) -> bool:
        if not dept_name:
            return False
        dept_name_lower = dept_name.strip().lower()
        for md in self.muted_depts:
            md_lower = md.lower()
            if md_lower in dept_name_lower:
                return True
        return False

    def get_muted_users(self) -> list[str]:
        return sorted(list(self.muted_users))

    def get_muted_depts(self) -> list[str]:
        return sorted(list(self.muted_depts))


mute_service = MuteService()
