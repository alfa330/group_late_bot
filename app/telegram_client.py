import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


class TelegramClient:
    async def _post(self, method: str, payload: dict) -> dict:
        url = f"{TELEGRAM_API}/{method}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.error("Telegram %s failed %s: %s", method, resp.status_code, resp.text)
            resp.raise_for_status()
        return resp.json()

    async def send_message(self, chat_id: str, text: str, reply_markup: dict = None) -> Optional[str]:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
            
        try:
            result = await self._post("sendMessage", payload)
            msg_id = str(result["result"]["message_id"])
            return msg_id
        except Exception as exc:
            logger.error("Failed to send message to %s: %s", chat_id, exc)
            return None

    async def send_document(self, chat_id: str, file_bytes: bytes, filename: str, caption: Optional[str] = None) -> Optional[str]:
        url = f"{TELEGRAM_API}/sendDocument"
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"
        files = {"document": (filename, file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, data=data, files=files)
            if resp.status_code != 200:
                logger.error("Telegram sendDocument failed %s: %s", resp.status_code, resp.text)
                resp.raise_for_status()
            result = resp.json()
            msg_id = str(result["result"]["message_id"])
            return msg_id
        except Exception as exc:
            logger.error("Failed to send document to %s: %s", chat_id, exc)
            return None

    async def edit_message_text(self, chat_id: str, message_id: str, text: str) -> bool:
        payload = {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": []}, # remove keyboard
        }
        try:
            await self._post("editMessageText", payload)
            return True
        except Exception as exc:
            logger.error("Failed to edit message %s: %s", message_id, exc)
            return False

    async def answer_callback_query(self, callback_query_id: str, text: str = "✅ Готово") -> None:
        try:
            await self._post(
                "answerCallbackQuery",
                {"callback_query_id": callback_query_id, "text": text},
            )
        except Exception as exc:
            logger.warning("answerCallbackQuery failed: %s", exc)

    async def set_webhook(self) -> dict:
        url = f"{settings.public_base_url}/telegram/webhook/{settings.telegram_webhook_secret}"
        result = await self._post("setWebhook", {"url": url})
        logger.info("Webhook set to: %s", url)
        return result


telegram_client = TelegramClient()
