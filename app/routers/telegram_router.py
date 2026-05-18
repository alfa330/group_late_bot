import logging

from fastapi import APIRouter, Request

from app.config import settings
from app.telegram_client import telegram_client
from app.services.chat_service import chat_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if secret != settings.telegram_webhook_secret:
        return {"ok": False}

    try:
        body = await request.json()
    except Exception:
        return {"ok": False}

    if "callback_query" in body:
        cq = body["callback_query"]
        callback_query_id = cq.get("id")
        data = cq.get("data", "")
        message = cq.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        message_id = str(message.get("message_id", ""))
        
        from_user = cq.get("from", {})
        first_name = from_user.get("first_name", "")
        username = from_user.get("username", "")
        reviewer_name = first_name or username or "Пользователь"

        if data == "review":
            original_text = message.get("text", "")
            
            # Simple text replacement to show it was reviewed
            if "📋 Статус: ожидает отбивки" in original_text:
                new_text = original_text.replace(
                    "📋 Статус: ожидает отбивки", 
                    f"✅ Статус: <b>отбито</b>\n👤 Отбил: {reviewer_name}"
                )
                await telegram_client.edit_message_text(chat_id, message_id, new_text)
                await telegram_client.answer_callback_query(callback_query_id, "✅ Отбито!")
            else:
                await telegram_client.answer_callback_query(callback_query_id, "ℹ️ Уже отбито")

        return {"ok": True}

    if "message" in body:
        msg = body["message"]
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = msg.get("text", "").strip()
        from_user = msg.get("from", {})
        user_id = str(from_user.get("id", ""))

        is_admin = (user_id == settings.default_telegram_chat_id) or (chat_id == settings.default_telegram_chat_id)

        if text.startswith("/start"):
            await telegram_client.send_message(
                chat_id,
                "👋 Привет! Я бот для отбивки опозданий.\n"
                f"Твой Chat ID: <code>{chat_id}</code>\n\n"
                "Администратор может использовать команды:\n"
                "/addchat [id] — добавить чат\n"
                "/delchat [id] — удалить чат\n"
                "/chats — список чатов"
            )
        elif text.startswith("/addchat"):
            if not is_admin:
                await telegram_client.send_message(chat_id, "❌ Нет прав.")
                return {"ok": True}
            
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_id = parts[1].strip()
                if chat_service.add_chat(target_id):
                    await telegram_client.send_message(chat_id, f"✅ Чат {target_id} успешно добавлен в список рассылки.")
                else:
                    await telegram_client.send_message(chat_id, f"ℹ️ Чат {target_id} уже есть в списке.")
            else:
                await telegram_client.send_message(chat_id, "Использование: /addchat [id]")
                
        elif text.startswith("/delchat"):
            if not is_admin:
                await telegram_client.send_message(chat_id, "❌ Нет прав.")
                return {"ok": True}
            
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_id = parts[1].strip()
                if chat_service.remove_chat(target_id):
                    await telegram_client.send_message(chat_id, f"🗑 Чат {target_id} удален из списка рассылки.")
                else:
                    await telegram_client.send_message(chat_id, f"❌ Чат {target_id} не найден или его нельзя удалить (это главный чат).")
            else:
                await telegram_client.send_message(chat_id, "Использование: /delchat [id]")
                
        elif text.startswith("/chats"):
            if not is_admin:
                await telegram_client.send_message(chat_id, "❌ Нет прав.")
                return {"ok": True}
            
            all_chats = chat_service.get_all_chats()
            chats_str = "\n".join([f"<code>{c}</code>" for c in all_chats])
            await telegram_client.send_message(chat_id, f"📋 <b>Список чатов для рассылки:</b>\n{chats_str}")

    return {"ok": True}
