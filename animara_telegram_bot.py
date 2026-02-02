#!/usr/bin/env python3
"""
🤖 ANIMARA TELEGRAM BOT v2.0
С персистентным управлением пользователями
"""

import os
import json
import re
import logging
import httpx
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CONFIG = {
    "bot_token": "628287747:AAETorXaNvstqJZSENiYHdlhZnvLrShyHmc",
    "owner_telegram_id": 237895794,
    "rag_proxy_url": "http://localhost:8015/v1/chat/completions",
    "secret_password": "animara2026",
    "session_duration_hours": 24,
    "users_file": os.path.expanduser("~/animara/workspace/USERS.json"),
}

# ═══════════════════════════════════════════════════════════════
# УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ
# ═══════════════════════════════════════════════════════════════

def load_users() -> dict:
    """Загружает пользователей из JSON файла"""
    try:
        if os.path.exists(CONFIG["users_file"]):
            with open(CONFIG["users_file"], "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠️ Error loading users: {e}")
    return {}

def save_users(users: dict):
    """Сохраняет пользователей в JSON файл"""
    try:
        os.makedirs(os.path.dirname(CONFIG["users_file"]), exist_ok=True)
        with open(CONFIG["users_file"], "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
        print(f"💾 Users saved: {len(users)} users")
    except Exception as e:
        print(f"❌ Error saving users: {e}")

USERS = load_users()
VERIFIED_SESSIONS = {}

ROLE_LEVELS = {
    "owner": 2, "admin": 2, "employee": 1, "friend": 1, "guest": 0, "unknown": -1
}

SENSITIVE_KEYWORDS = [
    "удали", "delete", "rm -rf", "добавь пользователя",
    "пароль", "password", "токен", "ключ", "все данные",
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# ФУНКЦИИ ДОСТУПА
# ═══════════════════════════════════════════════════════════════

def get_user_level(telegram_id: int) -> int:
    user_id_str = str(telegram_id)
    if user_id_str not in USERS:
        return -1
    
    user = USERS[user_id_str]
    base_level = ROLE_LEVELS.get(user.get("role", "guest"), 0)
    
    if telegram_id in VERIFIED_SESSIONS:
        if datetime.now() < VERIFIED_SESSIONS[telegram_id]:
            return max(base_level, 2)
        else:
            del VERIFIED_SESSIONS[telegram_id]
    return base_level

def get_person_id(telegram_id: int) -> str:
    user_id_str = str(telegram_id)
    if user_id_str in USERS:
        return USERS[user_id_str].get("person_id", f"telegram_{telegram_id}")
    return f"telegram_{telegram_id}"

def is_owner(telegram_id: int) -> bool:
    return telegram_id == CONFIG["owner_telegram_id"]

def is_sensitive_request(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in SENSITIVE_KEYWORDS)

# ═══════════════════════════════════════════════════════════════
# RAG PROXY
# ═══════════════════════════════════════════════════════════════

async def ask_rag(question: str, person_id: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                CONFIG["rag_proxy_url"],
                json={
                    "model": "qwen3",
                    "person_id": person_id,
                    "messages": [{"role": "user", "content": question}]
                }
            )
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            return content
    except Exception as e:
        logger.error(f"RAG error: {e}")
        return f"⚠️ Ошибка связи с RAG: {e}"

# ═══════════════════════════════════════════════════════════════
# КОМАНДЫ
# ═══════════════════════════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user_name = update.effective_user.first_name or "друг"
    level = get_user_level(telegram_id)
    
    if level < 0:
        await update.message.reply_text(
            f"👋 Привет! Я Animara.\n\n"
            f"Я тебя не знаю.\nТвой Telegram ID: `{telegram_id}`\n\n"
            f"Попроси владельца добавить тебя.",
            parse_mode="Markdown"
        )
    else:
        user_info = USERS.get(str(telegram_id), {})
        role = user_info.get("role", "guest")
        await update.message.reply_text(
            f"👋 Привет, {user_info.get('name', user_name)}!\n\n"
            f"Роль: {role}\nУровень: {level}\n\nЧем помочь?"
        )

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    
    if get_user_level(telegram_id) < 0:
        await update.message.reply_text("❌ Ты не в списке пользователей.")
        return
    
    if not context.args:
        await update.message.reply_text("🔐 Использование: /verify <пароль>")
        return
    
    password = " ".join(context.args)
    
    if password == CONFIG["secret_password"]:
        VERIFIED_SESSIONS[telegram_id] = datetime.now() + timedelta(hours=CONFIG["session_duration_hours"])
        await update.message.reply_text(f"✅ Level 2 на {CONFIG['session_duration_hours']} часов!")
    else:
        await update.message.reply_text("❌ Неверный пароль.")

async def adduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /adduser <telegram_id> <имя> <роль>"""
    telegram_id = update.effective_user.id
    
    if not is_owner(telegram_id):
        await update.message.reply_text("❌ Только владелец может добавлять пользователей.")
        return
    
    if len(context.args) < 3:
        await update.message.reply_text(
            "📝 Использование:\n"
            "`/adduser <telegram_id> <имя> <роль>`\n\n"
            "Роли: `owner`, `admin`, `employee`, `friend`, `guest`\n\n"
            "Пример:\n`/adduser 123456789 Вася friend`",
            parse_mode="Markdown"
        )
        return
    
    new_id = context.args[0]
    new_name = context.args[1]
    new_role = context.args[2].lower()
    
    if new_role not in ROLE_LEVELS:
        await update.message.reply_text(f"❌ Неизвестная роль: {new_role}")
        return
    
    USERS[new_id] = {
        "person_id": f"{new_role}_{new_name.lower()}",
        "name": new_name,
        "role": new_role,
        "level": ROLE_LEVELS[new_role],
        "added_at": datetime.now().strftime("%Y-%m-%d")
    }
    save_users(USERS)
    
    await update.message.reply_text(
        f"✅ Пользователь добавлен!\n\n"
        f"ID: `{new_id}`\nИмя: {new_name}\nРоль: {new_role}",
        parse_mode="Markdown"
    )

async def deluser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    
    if not is_owner(telegram_id):
        await update.message.reply_text("❌ Только владелец может удалять.")
        return
    
    if not context.args:
        await update.message.reply_text("📝 `/deluser <telegram_id>`", parse_mode="Markdown")
        return
    
    del_id = context.args[0]
    
    if del_id == str(CONFIG["owner_telegram_id"]):
        await update.message.reply_text("❌ Нельзя удалить владельца!")
        return
    
    if del_id in USERS:
        name = USERS[del_id].get("name", "Unknown")
        del USERS[del_id]
        save_users(USERS)
        await update.message.reply_text(f"✅ {name} удалён.")
    else:
        await update.message.reply_text(f"❌ ID {del_id} не найден.")

async def listusers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    
    if not is_owner(telegram_id):
        await update.message.reply_text("❌ Только владелец может смотреть список.")
        return
    
    lines = ["📋 **Пользователи:**\n"]
    emojis = {"owner": "👑", "admin": "⭐", "employee": "👷", "friend": "🤝", "guest": "👤"}
    
    for uid, info in USERS.items():
        e = emojis.get(info.get("role"), "❓")
        lines.append(f"{e} `{uid}` — {info.get('name')} ({info.get('role')})")
    
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    level = get_user_level(telegram_id)
    info = USERS.get(str(telegram_id), {})
    
    await update.message.reply_text(
        f"📊 **Статус**\n\n"
        f"ID: `{telegram_id}`\n"
        f"Имя: {info.get('name', '?')}\n"
        f"Роль: {info.get('role', 'unknown')}\n"
        f"Уровень: {level}",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════════════
# ОБРАБОТКА СООБЩЕНИЙ
# ═══════════════════════════════════════════════════════════════


def format_for_telegram(text: str) -> str:
    """Конвертирует Markdown от LLM в Telegram HTML"""
    import re
    
    # Убираем <think>...</think>
    text = re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)
    
    # **bold** → <b>bold</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    
    # *italic* → <i>italic</i>
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    
    # `code` → <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    
    # ```блок кода``` → <pre>код</pre>
    text = re.sub(r'```\w*\n?(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)
    
    # [текст](url) → <a href="url">текст</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    
    # ### заголовок → <b>заголовок</b>
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    
    # - список → • список
    text = re.sub(r'^\s*[-*]\s+', '• ', text, flags=re.MULTILINE)
    
    return text.strip()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    text = update.message.text
    level = get_user_level(telegram_id)
    
    if level < 0:
        await update.message.reply_text(
            f"👋 Я тебя не знаю.\nID: `{telegram_id}`\n\n"
            f"Попроси владельца:\n`/adduser {telegram_id} ТвоёИмя guest`",
            parse_mode="Markdown"
        )
        return
    
    if is_sensitive_request(text) and level < 2:
        await update.message.reply_text("🔐 Нужен Level 2. Используй `/verify <пароль>`", parse_mode="Markdown")
        return
    
    person_id = get_person_id(telegram_id)
    await update.message.chat.send_action("typing")
    
    response = await ask_rag(text, person_id)
    
    # Конвертируем Markdown → HTML для Telegram
    formatted = format_for_telegram(response)
    
    if len(formatted) > 4000:
        for i in range(0, len(formatted), 4000):
            try:
                await update.message.reply_text(formatted[i:i+4000], parse_mode="HTML")
            except Exception:
                await update.message.reply_text(formatted[i:i+4000])
    else:
        try:
            await update.message.reply_text(formatted, parse_mode="HTML")
        except Exception:
            # Fallback без форматирования если HTML сломан
            await update.message.reply_text(response)

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    global USERS
    USERS = load_users()
    
    owner_id = str(CONFIG["owner_telegram_id"])
    if owner_id not in USERS:
        USERS[owner_id] = {
            "person_id": "owner_sergey",
            "name": "Сергей",
            "role": "owner",
            "level": 2,
            "added_at": datetime.now().strftime("%Y-%m-%d")
        }
        save_users(USERS)
    
    print("=" * 50)
    print("🤖 ANIMARA TELEGRAM BOT v2.0")
    print(f"Users: {len(USERS)} | Owner: {CONFIG['owner_telegram_id']}")
    print("=" * 50)
    
    app = Application.builder().token(CONFIG["bot_token"]).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("verify", verify_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("adduser", adduser_command))
    app.add_handler(CommandHandler("deluser", deluser_command))
    app.add_handler(CommandHandler("users", listusers_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 Starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
