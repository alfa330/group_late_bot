from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    public_base_url: str = "http://localhost:8000"
    cron_secret: str
    telegram_bot_token: str
    telegram_webhook_secret: str
    default_telegram_chat_id: str
    admin_telegram_chat_ids: str = ""
    workpace_base_url: str = "https://api.workpace.kz"
    workpace_login: str
    workpace_password: str
    late_threshold_minutes: int = 1
    timezone: str = "Asia/Almaty"

    @property
    def admin_ids(self) -> set[str]:
        import re
        ids = set()
        if self.default_telegram_chat_id:
            parts = re.split(r"[,;]+", self.default_telegram_chat_id)
            ids.update(p.strip() for p in parts if p.strip())
        if self.admin_telegram_chat_ids:
            parts = re.split(r"[,;]+", self.admin_telegram_chat_ids)
            ids.update(p.strip() for p in parts if p.strip())
        return ids

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
