import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Token lifetimes (with a small buffer)
ACCESS_TOKEN_TTL_MINUTES = 28   # 30 min real, buffer 2 min
REFRESH_TOKEN_TTL_HOURS = 22    # 23 h real, buffer 1 h


class WorkpaceClient:
    def __init__(self):
        self.base_url = settings.workpace_base_url.rstrip("/")
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._access_expires_at: Optional[datetime] = None
        self._refresh_expires_at: Optional[datetime] = None

    # ------------------------------------------------------------------ auth

    async def login(self) -> None:
        """Perform login with login/password credentials."""
        url = f"{self.base_url}/api/auth/"
        payload = {
            "login": settings.workpace_login,
            "password": settings.workpace_password,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        self._store_tokens(data["accessToken"], data["refreshToken"])
        logger.info("Workpace login successful")

    async def refresh_token(self) -> bool:
        """Try refreshing tokens. Returns False if refresh failed."""
        if not self._refresh_token:
            return False
        url = f"{self.base_url}/api/auth/refresh"
        payload = {
            "accessToken": self._access_token,
            "refreshToken": self._refresh_token,
        }
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code != 200:
                    logger.warning("Workpace token refresh failed: %s", resp.status_code)
                    return False
                data = resp.json()
            self._store_tokens(data["accessToken"], data["refreshToken"])
            logger.info("Workpace token refreshed successfully")
            return True
        except Exception as exc:
            logger.error("Workpace refresh exception: %s", exc)
            return False

    def _store_tokens(self, access_token: str, refresh_token: str) -> None:
        now = datetime.utcnow()
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._access_expires_at = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
        self._refresh_expires_at = now + timedelta(hours=REFRESH_TOKEN_TTL_HOURS)

    def _is_access_valid(self) -> bool:
        if not self._access_token or not self._access_expires_at:
            return False
        return datetime.utcnow() < self._access_expires_at

    def _is_refresh_valid(self) -> bool:
        if not self._refresh_token or not self._refresh_expires_at:
            return False
        return datetime.utcnow() < self._refresh_expires_at

    async def get_valid_access_token(self) -> str:
        """Return a valid access token, refreshing or re-logging in as needed."""
        if self._is_access_valid():
            return self._access_token

        if self._is_refresh_valid():
            ok = await self.refresh_token()
            if ok:
                return self._access_token

        # Fall back to full login
        await self.login()
        return self._access_token

    # ---------------------------------------------------------- timetablespan

    async def get_timetable_span(
        self,
        start: datetime,
        end: datetime,
        skip: int = 0,
        take: int = 100,
    ) -> dict:
        """Single page request to /public/v1/timetablespan."""
        token = await self.get_valid_access_token()
        url = f"{self.base_url}/public/v1/timetablespan"
        params = {
            "Start": start.isoformat(),
            "End": end.isoformat(),
            "skip": skip,
            "take": take,
            "requireTotalCount": "true",
        }
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def get_all_timetable_spans(
        self, start: datetime, end: datetime, take: int = 100
    ) -> list[dict]:
        """Paginate through all timetablespan records for the given period."""
        all_records: list[dict] = []
        skip = 0
        total_count: Optional[int] = None

        while True:
            data = await self.get_timetable_span(start, end, skip=skip, take=take)
            records = data.get("data", [])
            all_records.extend(records)

            if total_count is None:
                total_count = data.get("totalCount")

            skip += len(records)

            if not records:
                break
            if total_count is not None and skip >= total_count:
                break

        logger.info(
            "Fetched %d timetablespan records (totalCount=%s)",
            len(all_records),
            total_count,
        )
        return all_records

    # ---------------------------------------------------------------- employee

    async def get_employee(
        self,
        skip: int = 0,
        take: int = 100,
        active_only: bool = True,
    ) -> dict:
        """Single page request to /public/v1/employee."""
        import json

        token = await self.get_valid_access_token()
        url = f"{self.base_url}/public/v1/employee"
        params = {
            "skip": skip,
            "take": take,
            "requireTotalCount": "true",
        }
        if active_only:
            params["filter"] = json.dumps(["isArchived", "=", False])

        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def get_all_employees(
        self, take: int = 100, active_only: bool = True
    ) -> list[dict]:
        """Paginate through /public/v1/employee records."""
        all_records: list[dict] = []
        skip = 0
        total_count: Optional[int] = None

        while True:
            data = await self.get_employee(skip=skip, take=take, active_only=active_only)
            records = data.get("data", [])
            all_records.extend(records)

            if total_count is None:
                total_count = data.get("totalCount")

            skip += len(records)

            if not records:
                break
            if total_count is not None and skip >= total_count:
                break

        logger.info(
            "Fetched %d employee records (totalCount=%s)",
            len(all_records),
            total_count,
        )
        return all_records

    # ------------------------------------------------------------------ mark

    async def get_domain_mark(
        self,
        start: datetime,
        end: datetime,
        skip: int = 0,
        take: int = 100,
    ) -> dict:
        """Single page request to /domain-api/mark using DevExtreme filters."""
        import json
        token = await self.get_valid_access_token()
        url = f"{self.base_url}/domain-api/mark"
        
        # DevExtreme filter format
        filter_arr = [
            ["markDate", ">=", start.isoformat()],
            "and",
            ["markDate", "<=", end.isoformat()]
        ]
        
        params = {
            "filter": json.dumps(filter_arr),
            "requireTotalCount": "true",
            "skip": skip,
            "take": take,
        }

        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def get_all_domain_marks(
        self, start: datetime, end: datetime, take: int = 100
    ) -> list[dict]:
        """Paginate through /domain-api/mark records."""
        all_records: list[dict] = []
        skip = 0
        total_count: Optional[int] = None

        while True:
            data = await self.get_domain_mark(start, end, skip=skip, take=take)
            records = data.get("data", [])
            all_records.extend(records)

            if total_count is None:
                total_count = data.get("totalCount")

            skip += len(records)

            if not records:
                break
            if total_count is not None and skip >= total_count:
                break

        logger.info(
            "Fetched %d domain mark records (totalCount=%s)",
            len(all_records),
            total_count,
        )
        return all_records


# Singleton instance shared across the app
workpace_client = WorkpaceClient()
