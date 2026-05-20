import logging
import time
from typing import Optional

from fastapi import APIRouter, Request

from app.config import settings
from app.telegram_client import telegram_client
from app.services.chat_service import chat_service
from app.services.department_service import get_department_names
from app.services.mute_service import mute_service

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


def _can_manage_mutes(is_admin: bool, chat_type: str) -> bool:
    return is_admin or chat_type == "private"


def _mute_scope_chat_id(chat_id: str, is_admin: bool) -> Optional[str]:
    return None if is_admin else chat_id


def _mute_scope_label(is_admin: bool) -> str:
    return "глобально" if is_admin else "для вашего чата"


def _admin_chat_scope_from_args(text: str, is_admin: bool) -> tuple[Optional[str], bool]:
    parts = text.split(maxsplit=1)
    if is_admin and len(parts) == 2:
        return parts[1].strip(), True
    return None, False


async def _send_department_list(chat_id: str):
    departments = await get_department_names()
    if not departments:
        await telegram_client.send_message(chat_id, "ℹ️ В Workpace не найдено активных отделов.")
        return

    header = f"🏢 <b>Отделы Workpace ({len(departments)}):</b>\n"
    lines = [f"• <code>{department}</code>" for department in departments]
    chunk = header
    for line in lines:
        if len(chunk) + len(line) + 1 > 3900:
            await telegram_client.send_message(chat_id, chunk)
            chunk = header
        chunk += f"{line}\n"
    if chunk.strip() != header.strip():
        await telegram_client.send_message(chat_id, chunk)


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
        chat_type = chat.get("type", "")
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
                "• <code>/help</code> — подробная инструкция по использованию системы\n"
                "• <code>/report</code> — получить отчет за сегодня\n"
                "• <code>/report ГГГГ-ММ-ДД</code> — получить отчет за указанную дату (например: <code>/report 2026-05-18</code>)\n"
                "• <code>/mute_user [ФИО]</code> — не получать отбивки по сотруднику\n"
                "• <code>/unmute_user [ФИО]</code> — снова получать отбивки по сотруднику\n"
                "• <code>/mute_dept [Отдел]</code> — не получать отбивки по отделу\n"
                "• <code>/unmute_dept [Отдел]</code> — снова получать отбивки по отделу\n"
                "• <code>/mute_all</code> — отключить все уведомления\n"
                "• <code>/unmute_all</code> — снова включить все уведомления\n"
                "• <code>/muted</code> — ваши отключенные отбивки\n\n"
                "<b>Администратор может использовать команды:</b>\n"
                "• <code>/addchat [id]</code> — добавить чат в список рассылки\n"
                "• <code>/delchat [id]</code> — удалить чат из списка рассылки\n"
                "• <code>/setchatdept [id] [Отдел]</code> — закрепить чат за отделом\n"
                "• <code>/setdept [Отдел]</code> — закрепить текущий чат за отделом\n"
                "• <code>/clearchatdept [id]</code> — убрать фильтр отдела у чата\n"
                "• <code>/cleardept</code> — убрать фильтр отдела у текущего чата\n"
                "• <code>/chats</code> — список разрешенных чатов\n"
                "• <code>/departments</code> — список отделов Workpace\n"
                "• те же mute-команды — глобально управлять отбивками для всех чатов"
            )
        elif text.startswith("/help"):
            help_text = (
                "ℹ️ <b>Информационная система Group Late Bot</b>\n\n"
                "Автоматизированный инструмент для мониторинга трудовой дисциплины и учета рабочего времени сотрудников (интеграция с платформой <b>Workpace</b>).\n\n"
                "📌 <b>Основные возможности системы:</b>\n"
                "• <b>Оперативный аудит (каждые 2 минуты):</b> Автоматическая отправка уведомлений в рабочие чаты об опозданиях, ранних уходах, неявках и подозрительных биометрических отметках.\n"
                "• <b>Интерактивная координация:</b> Руководители могут подтвердить инцидент, нажав кнопку <b>«Отбито»</b> непосредственно в чате Telegram.\n"
                "• <b>Автоматическая отчетность:</b> Выгрузка детальных Excel-файлов с подсчетом отработанного времени по факту первого/последнего прикосновений к терминалу, отклонений от нормы смен и автовыделением статусов цветом.\n"
                "• <b>Аналитика за период:</b> Многостраничные сводные отчеты за диапазон дат со сводной аналитикой (дашбордом) по каждому сотруднику.\n\n"
                "📂 <b>Доступные форматы команды /report:</b>\n"
                "• <code>/report</code> — за текущий день (по всем отделам)\n"
                "• <code>/report [Отдел]</code> — за сегодня по конкретному отделу\n"
                "• <code>/report YYYY-MM-DD</code> — за дату по всем отделам\n"
                "• <code>/report YYYY-MM-DD [Отдел]</code> — за дату по отделу\n"
                "• <code>/report YYYY-MM-DD YYYY-MM-DD</code> — за период по всем отделам\n"
                "• <code>/report YYYY-MM-DD YYYY-MM-DD [Отдел]</code> — за период по отделу\n\n"
                "⚙️ <b>Персональные настройки отбивок:</b>\n"
                "• <code>/mute_user [ФИО]</code> — не получать отбивки по сотруднику\n"
                "• <code>/unmute_user [ФИО]</code> — снова получать отбивки по сотруднику\n"
                "• <code>/mute_dept [Отдел]</code> — не получать отбивки по отделу\n"
                "• <code>/unmute_dept [Отдел]</code> — снова получать отбивки по отделу\n"
                "• <code>/mute_all</code> — отключить все уведомления\n"
                "• <code>/unmute_all</code> — снова включить все уведомления\n"
                "• <code>/muted</code> — посмотреть свои отключенные отбивки\n"
                "<i>Обычные пользователи настраивают только личный чат с ботом. Администратор применяет эти команды глобально.</i>\n\n"
                "🏢 <b>Отделы и чаты:</b>\n"
                "• <code>/departments</code> — список отделов Workpace\n"
                "• <code>/setchatdept [Chat ID] [Отдел]</code> — отправлять в чат только уведомления выбранного отдела\n"
                "• <code>/setdept [Отдел]</code> — сделать текущий чат чатом выбранного отдела\n"
                "• <code>/clearchatdept [Chat ID]</code> — снова отправлять в чат все отделы\n"
                "• <code>/cleardept</code> — снять фильтр отдела с текущего чата\n\n"
                "<i>*Пример: <code>/report 2026-05-18 2026-05-20 Контакт-центр</code></i>"
            )
            await telegram_client.send_message(chat_id, help_text)
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
                    "• <code>/report ГГГГ-ММ-ДД</code> — получить отчет за указанную дату (например: <code>/report 2026-05-18</code>)\n\n"
                    "<i>Администратор может закрепить чат за отделом командой /setchatdept.</i>"
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
            chat_lines = []
            for c in all_chats:
                line = chat_service.format_chat_line(c)
                if mute_service.get_all_muted(c):
                    line += " — уведомления отключены"
                chat_lines.append(line)
            chats_str = "\n".join(chat_lines)
            global_mute_text = "\n🔕 <b>Глобально все уведомления отключены.</b>\n" if mute_service.get_all_muted() else "\n"
            await telegram_client.send_message(chat_id, f"📋 <b>Список чатов для рассылки:</b>{global_mute_text}{chats_str}")

        elif text.startswith("/setchatdept"):
            if not is_admin:
                await telegram_client.send_message(chat_id, "❌ Нет прав.")
                return {"ok": True}

            parts = text.split(maxsplit=2)
            if len(parts) == 3:
                target_id = parts[1].strip()
                target_dept = parts[2].strip()
                if chat_service.set_chat_department(target_id, target_dept):
                    await telegram_client.send_message(chat_id, f"✅ Чат <code>{target_id}</code> закреплен за отделом <b>{target_dept}</b>. Теперь туда будут уходить только уведомления этого отдела.")
                else:
                    await telegram_client.send_message(chat_id, f"❌ Не удалось настроить чат <code>{target_id}</code>. Проверьте, что он добавлен через /addchat и отдел указан полностью.")
            else:
                await telegram_client.send_message(chat_id, "Использование: /setchatdept [Chat ID] [Название отдела]")

        elif text.startswith("/setdept"):
            if not is_admin:
                await telegram_client.send_message(chat_id, "❌ Нет прав.")
                return {"ok": True}

            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_dept = parts[1].strip()
                if chat_service.set_chat_department(chat_id, target_dept):
                    await telegram_client.send_message(chat_id, f"✅ Текущий чат закреплен за отделом <b>{target_dept}</b>. Теперь сюда будут уходить только уведомления этого отдела.")
                else:
                    await telegram_client.send_message(chat_id, "❌ Не удалось настроить текущий чат. Проверьте, что он добавлен через /addchat и отдел указан полностью.")
            else:
                await telegram_client.send_message(chat_id, "Использование: /setdept [Название отдела]")

        elif text.startswith("/clearchatdept"):
            if not is_admin:
                await telegram_client.send_message(chat_id, "❌ Нет прав.")
                return {"ok": True}

            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_id = parts[1].strip()
                if chat_service.clear_chat_department(target_id):
                    await telegram_client.send_message(chat_id, f"✅ Фильтр отдела для чата <code>{target_id}</code> снят. Чат снова получает все отделы.")
                else:
                    await telegram_client.send_message(chat_id, f"ℹ️ У чата <code>{target_id}</code> нет фильтра отдела или чат не найден.")
            else:
                await telegram_client.send_message(chat_id, "Использование: /clearchatdept [Chat ID]")

        elif text.startswith("/cleardept"):
            if not is_admin:
                await telegram_client.send_message(chat_id, "❌ Нет прав.")
                return {"ok": True}

            if chat_service.clear_chat_department(chat_id):
                await telegram_client.send_message(chat_id, "✅ Фильтр отдела для текущего чата снят. Чат снова получает все отделы.")
            else:
                await telegram_client.send_message(chat_id, "ℹ️ У текущего чата нет фильтра отдела или чат не найден.")

        elif text.startswith("/departments") or text.startswith("/depts"):
            all_chats = chat_service.get_all_chats()
            if chat_id not in all_chats and not is_admin:
                await telegram_client.send_message(chat_id, "❌ Этот чат не зарегистрирован в системе рассылки.")
                return {"ok": True}
            try:
                await _send_department_list(chat_id)
            except Exception as exc:
                logger.error("Failed to fetch departments: %s", exc)
                await telegram_client.send_message(chat_id, f"❌ Не удалось получить список отделов Workpace:\n<code>{exc}</code>")

        elif text.startswith("/mute_all"):
            if not _can_manage_mutes(is_admin, chat_type):
                await telegram_client.send_message(
                    chat_id,
                    "❌ Персональные настройки уведомлений доступны только в личном чате с ботом. "
                    "Напишите боту /start и используйте команду там."
                )
                return {"ok": True}

            target_chat_id, explicit_chat = _admin_chat_scope_from_args(text, is_admin)
            if explicit_chat and target_chat_id not in chat_service.get_all_chats():
                await telegram_client.send_message(chat_id, f"❌ Чат <code>{target_chat_id}</code> не найден в списке рассылки.")
                return {"ok": True}
            scope_chat_id = target_chat_id if explicit_chat else _mute_scope_chat_id(chat_id, is_admin)
            scope_label = f"для чата <code>{target_chat_id}</code>" if explicit_chat else _mute_scope_label(is_admin)
            if mute_service.mute_all(scope_chat_id):
                await telegram_client.send_message(chat_id, f"🔕 Все уведомления отключены {scope_label}.")
            else:
                await telegram_client.send_message(chat_id, f"ℹ️ Все уведомления уже отключены {scope_label}.")

        elif text.startswith("/unmute_all"):
            if not _can_manage_mutes(is_admin, chat_type):
                await telegram_client.send_message(
                    chat_id,
                    "❌ Персональные настройки уведомлений доступны только в личном чате с ботом. "
                    "Напишите боту /start и используйте команду там."
                )
                return {"ok": True}

            target_chat_id, explicit_chat = _admin_chat_scope_from_args(text, is_admin)
            if explicit_chat and target_chat_id not in chat_service.get_all_chats():
                await telegram_client.send_message(chat_id, f"❌ Чат <code>{target_chat_id}</code> не найден в списке рассылки.")
                return {"ok": True}
            scope_chat_id = target_chat_id if explicit_chat else _mute_scope_chat_id(chat_id, is_admin)
            scope_label = f"для чата <code>{target_chat_id}</code>" if explicit_chat else _mute_scope_label(is_admin)
            if mute_service.unmute_all(scope_chat_id):
                await telegram_client.send_message(chat_id, f"🔔 Все уведомления снова включены {scope_label}.")
            else:
                await telegram_client.send_message(chat_id, f"ℹ️ Все уведомления не были отключены {scope_label}.")
            
        elif text.startswith("/mute_user"):
            if not _can_manage_mutes(is_admin, chat_type):
                await telegram_client.send_message(
                    chat_id,
                    "❌ Персональные настройки уведомлений доступны только в личном чате с ботом. "
                    "Напишите боту /start и используйте команду там."
                )
                return {"ok": True}

            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_user = parts[1].strip()
                scope_chat_id = _mute_scope_chat_id(chat_id, is_admin)
                scope_label = _mute_scope_label(is_admin)
                if mute_service.mute_user(target_user, scope_chat_id):
                    await telegram_client.send_message(chat_id, f"🔇 Отбивки по сотруднику <b>{target_user}</b> отключены {scope_label}.")
                else:
                    await telegram_client.send_message(chat_id, f"ℹ️ Сотрудник <b>{target_user}</b> уже находится в списке отключенных {scope_label}.")
            else:
                await telegram_client.send_message(chat_id, "Использование: /mute_user [ФИО сотрудника]")

        elif text.startswith("/unmute_user"):
            if not _can_manage_mutes(is_admin, chat_type):
                await telegram_client.send_message(
                    chat_id,
                    "❌ Персональные настройки уведомлений доступны только в личном чате с ботом. "
                    "Напишите боту /start и используйте команду там."
                )
                return {"ok": True}

            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_user = parts[1].strip()
                scope_chat_id = _mute_scope_chat_id(chat_id, is_admin)
                scope_label = _mute_scope_label(is_admin)
                if mute_service.unmute_user(target_user, scope_chat_id):
                    await telegram_client.send_message(chat_id, f"🔊 Отбивки по сотруднику <b>{target_user}</b> снова включены {scope_label}.")
                else:
                    await telegram_client.send_message(chat_id, f"❌ Сотрудник <b>{target_user}</b> не найден в списке отключенных {scope_label}.")
            else:
                await telegram_client.send_message(chat_id, "Использование: /unmute_user [ФИО сотрудника]")

        elif text.startswith("/mute_dept"):
            if not _can_manage_mutes(is_admin, chat_type):
                await telegram_client.send_message(
                    chat_id,
                    "❌ Персональные настройки уведомлений доступны только в личном чате с ботом. "
                    "Напишите боту /start и используйте команду там."
                )
                return {"ok": True}

            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_dept = parts[1].strip()
                scope_chat_id = _mute_scope_chat_id(chat_id, is_admin)
                scope_label = _mute_scope_label(is_admin)
                if mute_service.mute_dept(target_dept, scope_chat_id):
                    await telegram_client.send_message(chat_id, f"🔇 Отбивки по отделу <b>{target_dept}</b> отключены {scope_label}.")
                else:
                    await telegram_client.send_message(chat_id, f"ℹ️ Отдел <b>{target_dept}</b> уже находится в списке отключенных {scope_label}.")
            else:
                await telegram_client.send_message(chat_id, "Использование: /mute_dept [Название отдела]")

        elif text.startswith("/unmute_dept"):
            if not _can_manage_mutes(is_admin, chat_type):
                await telegram_client.send_message(
                    chat_id,
                    "❌ Персональные настройки уведомлений доступны только в личном чате с ботом. "
                    "Напишите боту /start и используйте команду там."
                )
                return {"ok": True}

            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                target_dept = parts[1].strip()
                scope_chat_id = _mute_scope_chat_id(chat_id, is_admin)
                scope_label = _mute_scope_label(is_admin)
                if mute_service.unmute_dept(target_dept, scope_chat_id):
                    await telegram_client.send_message(chat_id, f"🔊 Отбивки по отделу <b>{target_dept}</b> снова включены {scope_label}.")
                else:
                    await telegram_client.send_message(chat_id, f"❌ Отдел <b>{target_dept}</b> не найден в списке отключенных {scope_label}.")
            else:
                await telegram_client.send_message(chat_id, "Использование: /unmute_dept [Название отдела]")

        elif text.startswith("/muted") or text.startswith("/mutes"):
            if not _can_manage_mutes(is_admin, chat_type):
                await telegram_client.send_message(
                    chat_id,
                    "❌ Персональные настройки уведомлений доступны только в личном чате с ботом. "
                    "Напишите боту /start и используйте команду там."
                )
                return {"ok": True}

            scope_chat_id = _mute_scope_chat_id(chat_id, is_admin)
            all_muted = mute_service.get_all_muted(scope_chat_id)
            muted_users = mute_service.get_muted_users(scope_chat_id)
            muted_depts = mute_service.get_muted_depts(scope_chat_id)

            title = "📋 <b>Глобально отключенные отбивки:</b>\n" if is_admin else "📋 <b>Ваши отключенные отбивки:</b>\n"
            response_parts = [title]

            response_parts.append("🔕 <b>Все уведомления:</b>")
            response_parts.append("• <b>отключены</b>" if all_muted else "• <i>включены</i>")

            response_parts.append("👤 <b>Сотрудники:</b>")
            if muted_users:
                for u in muted_users:
                    response_parts.append(f"• <code>{u}</code>")
            else:
                response_parts.append("<i>список пуст</i>")

            response_parts.append("\n🏢 <b>Отделы:</b>")
            if muted_depts:
                for d in muted_depts:
                    response_parts.append(f"• <code>{d}</code>")
            else:
                response_parts.append("<i>список пуст</i>")

            await telegram_client.send_message(chat_id, "\n".join(response_parts))

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

            chat_department = chat_service.get_chat_department(chat_id)
            if chat_department and not is_admin:
                chat_dept_lower = chat_department.casefold()
                dept_filter_lower = dept_filter.casefold() if dept_filter else ""
                if dept_filter and chat_dept_lower not in dept_filter_lower and dept_filter_lower not in chat_dept_lower:
                    await telegram_client.send_message(chat_id, f"❌ Этот чат закреплен за отделом <b>{chat_department}</b>. Отчет можно получить только по этому отделу.")
                    return {"ok": True}
                dept_filter = dept_filter or chat_department
                
            await telegram_client.send_message(chat_id, "⏳ <i>Генерирую Excel-отчет, пожалуйста подождите...</i>")
            from app.services.report_service import generate_report
            file_bytes, filename, report_text = await generate_report(start_date_str, end_date_str, dept_filter)
            
            if file_bytes:
                await telegram_client.send_document(chat_id, file_bytes, filename, report_text)
            else:
                await telegram_client.send_message(chat_id, report_text)

    return {"ok": True}
