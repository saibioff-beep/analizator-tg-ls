#!/usr/bin/env python3
"""
Telegram Business Bot - Private Chat Monitor + Grok Analysis
"""

import os
import logging
from datetime import datetime
from typing import Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, BufferedInputFile, Update
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from dotenv import load_dotenv

from database import (
    init_db,
    save_business_connection,
    disable_business_connection,
    save_business_message,
    get_user_business_chats,
    get_messages_for_analysis
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://your-bot.bothost.ru/webhook
WEBHOOK_PATH = "/webhook"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ==================== BUSINESS UPDATE HANDLERS ====================

@router.business_connection()
async def handle_business_connection(business_connection):
    """Handle when user connects or disconnects the bot."""
    user_id = business_connection.user.id
    conn_id = business_connection.id
    chat = business_connection.chat
    is_enabled = business_connection.is_enabled

    if is_enabled:
        await save_business_connection(
            user_id=user_id,
            business_connection_id=conn_id,
            chat_id=chat.id,
            chat_title=chat.title or chat.username or str(chat.id)
        )
        logger.info(f"Business connection enabled: {conn_id} for user {user_id}")
    else:
        await disable_business_connection(conn_id)
        logger.info(f"Business connection disabled: {conn_id}")


@router.business_message()
async def handle_business_message(message: Message):
    """Log business messages."""
    if not message.business_connection:
        return

    conn_id = message.business_connection.id
    chat_id = message.chat.id
    text = message.text or message.caption or ""

    await save_business_message(
        business_connection_id=conn_id,
        chat_id=chat_id,
        message_id=message.message_id,
        from_user_id=message.from_user.id if message.from_user else None,
        from_username=message.from_user.username if message.from_user else None,
        text=text,
        is_outgoing=message.from_user.id == message.bot.id if message.from_user else False,
        timestamp=message.date.isoformat() if message.date else None
    )


# ==================== PRIVATE CHAT COMMANDS ====================

@router.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.type != "private":
        return

    chats = await get_user_business_chats(message.from_user.id)
    
    if not chats:
        text = (
            "👋 Привет! Я Business Bot для анализа личных чатов.\n\n"
            "Чтобы я начал видеть твои сообщения:\n"
            "1. Зайди в настройки Telegram → Автоматизация чатов\n"
            "2. Подключи этого бота к нужным чатам\n\n"
            "После подключения я буду логировать сообщения и смогу делать анализ через Grok."
        )
    else:
        text = f"✅ Ты подключил меня к {len(chats)} чатам.\n\n"
        text += "Доступные команды:\n"
        text += "• /chats — список подключённых чатов\n"
        text += "• /prepare_grok [номер] — подготовить анализ\n"
        text += "• /help — справка"

    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message):
    if message.chat.type != "private":
        return

    text = (
        "<b>Команды бота (Business версия):</b>\n\n"
        "• <code>/chats</code> — список подключённых чатов\n"
        "• <code>/prepare_grok [номер]</code> — подготовить лог для Grok\n"
        "• <code>/export [номер]</code> — скачать файл с сообщениями\n\n"
        "Сначала подключи бота в настройках Telegram → Автоматизация чатов."
    )
    await message.answer(text)


@router.message(Command("chats"))
async def cmd_chats(message: Message):
    if message.chat.type != "private":
        return

    chats = await get_user_business_chats(message.from_user.id)
    if not chats:
        await message.answer("У тебя пока нет подключённых чатов.\nПодключи бота в настройках Telegram.")
        return

    text = "<b>Твои подключённые чаты:</b>\n\n"
    for i, chat in enumerate(chats, 1):
        text += f"{i}. {chat['chat_title']} (ID: <code>{chat['chat_id']}</code>)\n"

    text += "\nИспользуй номер для анализа: <code>/prepare_grok 1</code>"
    await message.answer(text)


@router.message(Command("prepare_grok"))
async def cmd_prepare_grok(message: Message, command: CommandObject):
    if message.chat.type != "private":
        return

    chats = await get_user_business_chats(message.from_user.id)
    if not chats:
        await message.answer("Сначала подключи бота к чатам через настройки Telegram.")
        return

    # Parse which chat
    chat_index = 1
    if command.args:
        try:
            chat_index = int(command.args.split()[0])
        except:
            pass

    if chat_index < 1 or chat_index > len(chats):
        await message.answer(f"Неверный номер. У тебя {len(chats)} чатов.")
        return

    selected_chat = chats[chat_index - 1]
    conn_id = selected_chat['business_connection_id']

    msgs = await get_messages_for_analysis(conn_id, limit=300)

    if not msgs:
        await message.answer("В этом чате пока нет сохранённых сообщений.")
        return

    # Build log for Grok
    lines = [f"ЧАТ ДЛЯ АНАЛИЗА У GROK\n"]
    lines.append(f"Чат: {selected_chat['chat_title']}")
    lines.append(f"Сообщений: {len(msgs)}\n")

    for m in msgs:
        ts = m['timestamp'][:19].replace('T', ' ')
        direction = "Я" if m['is_outgoing'] else "Собеседник"
        lines.append(f"[{ts}] {direction}: {m['text'] or '[медиа]'}")

    content = "\n".join(lines)
    filename = f"grok_analysis_{selected_chat['chat_id']}.txt"
    file = BufferedInputFile(content.encode("utf-8"), filename=filename)

    await message.answer_document(
        document=file,
        caption=f"✅ Лог для Grok готов ({len(msgs)} сообщений).\nОтправь мне этот файл с вопросом для анализа."
    )


# ==================== WEBHOOK SETUP ====================

async def on_startup():
    await init_db()
    if WEBHOOK_URL:
        await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}")
        logger.info(f"Webhook set to {WEBHOOK_URL}{WEBHOOK_PATH}")
    else:
        logger.warning("WEBHOOK_URL not set. Running in polling mode (not recommended for Business Bot).")


async def main():
    dp.startup.register(on_startup)

    if WEBHOOK_URL:
        # Webhook mode (recommended)
        app = web.Application()
        webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        webhook_handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        web.run_app(app, host="0.0.0.0", port=8080)
    else:
        # Fallback to polling (not ideal for Business)
        await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
