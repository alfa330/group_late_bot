import logging
import time

from fastapi import APIRouter, Request

from app.config import settings
from app.telegram_client import telegram_client
from app.services.chat_service import chat_service

logger = logging.getLogger(__name__)
router = APIRouter()

PROCESSED_UPDATES = set()

def _deduplicate_update(update_id: int) -> bool:
    if not update_id:
        return False
    if update_id in PROCESSED_UPDATES:
        return True
    if len(PROCESSED_UPDATES) > 2000:
        PROCESSED_UPDATES.clear()
    PROCESSED_UPDATES.add(update_id)
    return False


@router.post("/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if secret != settings.telegram_webhook_secret:
        return {"ok": False}

    try:
        body = await request.json()
    except Exception:
        return {"ok": False}

    update_id = body.get("update_id")
    if update_id and _deduplicate_update(update_id):
        logger.info("Duplicate Telegram webhook update %s ignored.", update_id)
        return {"ok": True}

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
        
        # Ignore old messages from Telegram queue (older than 60 seconds)
        msg_date = msg.get("date", 0)
        current_time = time.time()
        if msg_date > 0 and (current_time - msg_date) > 60:
            logger.info("Ignoring old Telegram message: sent %s seconds ago.", int(current_time - msg_date))
            return {"ok": True}

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
                "<b>Доступные команды:</b>\n"
                "• <code>/report</code> — получить отчет за сегодня\n"
                "• <code>/report ГГГГ-ММ-ДД</code> — получить отчет за указанную дату (например: <code>/report 2026-05-18</code>)\n\n"
                "<b>Администратор может использовать команды:</b>\n"
                "• <code>/addchat [id]</code> — добавить чат в список рассылки\n"
                "• <code>/delchat [id]</code> — удалить чат из списка рассылки\n"
                "• <code>/chats</code> — список разрешенных чатов"
            )
        elif text.startswith("/addchat"):
            if not is_admin:
                await telegram_client.send_message(chat_id, "❌ Нет прав.")
                return {"ok": True}
            
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_id = parts[1].strip()
                
                # Proactively send welcome message to verify connectivity
                welcome_text = (
                    "🎉 <b>Этот чат успешно добавлен в список рассылки бота Workpace!</b>\n\n"
                    "Теперь сюда будут приходить уведомления о нарушениях.\n\n"
                    "<b>Доступные команды для всех участников:</b>\n"
                    "• <code>/report</code> — получить отчет за сегодня\n"
                    "• <code>/report ГГГГ-ММ-ДД</code> — получить отчет за указанную дату (например: <code>/report 2026-05-18</code>)"
                )
                try:
                    msg_id = await telegram_client.send_message(target_id, welcome_text)
                    if msg_id:
                        if chat_service.add_chat(target_id):
                            await telegram_client.send_message(chat_id, f"✅ Чат {target_id} успешно добавлен в список рассылки. Приветственное сообщение отправлено!")
                        else:
                            await telegram_client.send_message(chat_id, f"ℹ️ Чат {target_id} уже есть в списке. Приветственное сообщение отправлено повторно!")
                    else:
                        await telegram_client.send_message(chat_id, f"❌ Безуспешно. Бот не смог отправить сообщение в чат {target_id}. Проверьте, что бот состоит в этом чате и имеет права на отправку.")
                except Exception as exc:
                    logger.error("Failed to add chat %s: %s", target_id, exc)
                    await telegram_client.send_message(chat_id, f"❌ Безуспешно. Не удалось написать в чат {target_id}.\nОшибка: <code>{exc}</code>")
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
            
        elif text.startswith("/report"):
            all_chats = chat_service.get_all_chats()
            if chat_id not in all_chats and not is_admin:
                await telegram_client.send_message(chat_id, "❌ Этот чат не зарегистрирован в системе рассылки.")
                return {"ok": True}
                
            parts = text.split()
            args = parts[1:]
            
            from datetime import datetime
            import pytz
            import re
            TZ = pytz.timezone(settings.timezone)
            today_str = datetime.now(TZ).strftime("%Y-%m-%d")
            
            start_date_str = today_str
            end_date_str = None
            dept_filter = None
            
            def is_date(s):
                return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s))
            
            if len(args) == 1:
                if is_date(args[0]):
                    start_date_str = args[0]
                else:
                    dept_filter = args[0]
            elif len(args) == 2:
                if is_date(args[0]) and is_date(args[1]):
                    start_date_str = args[0]
                    end_date_str = args[1]
                elif is_date(args[0]):
                    start_date_str = args[0]
                    dept_filter = args[1]
                else:
                    dept_filter = " ".join(args)
            elif len(args) >= 3:
                if is_date(args[0]) and is_date(args[1]):
                    start_date_str = args[0]
                    end_date_str = args[1]
                    dept_filter = " ".join(args[2:])
                elif is_date(args[0]):
                    start_date_str = args[0]
                    dept_filter = " ".join(args[1:])
                else:
                    dept_filter = " ".join(args)
                
            await telegram_client.send_message(chat_id, "⏳ <i>Генерирую Excel-отчет, пожалуйста подождите...</i>")
            from app.services.report_service import generate_report
            file_bytes, filename, report_text = await generate_report(start_date_str, end_date_str, dept_filter)
            
            if file_bytes:
                await telegram_client.send_document(chat_id, file_bytes, filename, report_text)
            else:
                await telegram_client.send_message(chat_id, report_text)

    return {"ok": True}
