import os
import sqlite3
import re
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp
import asyncio
from datetime import datetime, timedelta

# Настройки
DATABASE_NAME = 'urls.db'
USER_DATABASE_NAME = 'users.db'

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))

def create_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS urls (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL UNIQUE)''')
    conn.commit()
    conn.close()

def create_user_db():
    conn = sqlite3.connect(USER_DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

def clean_url(url):
    return url.replace("http://", "").replace("https://", "").rstrip('/')

def format_url(url):
    if not url.startswith(('http://', 'https://')):
        return f'https://{url}'
    return url

def is_valid_url(url):
    regex = re.compile(
        r'^(?:http|ftp)s?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'  # ...or ipv4
        r'\[?[A-F0-9]*:[A-F0-9:]+\]?)'  # ...or ipv6
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

def get_all_urls():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT url FROM urls')
    urls = [row[0] for row in cursor.fetchall()]
    conn.close()
    return urls

def add_url(url):
    formatted_url = format_url(url)
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO urls (url) VALUES (?)', (formatted_url,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def delete_url(url):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM urls WHERE url = ?', (url,))
    conn.commit()
    conn.close()

def save_chat_id(chat_id):
    conn = sqlite3.connect(USER_DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (chat_id) VALUES (?)', (chat_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def get_all_chat_ids():
    conn = sqlite3.connect(USER_DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM users')
    chat_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return chat_ids

async def check_website(session, url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with session.get(url, headers=headers, timeout=15) as response:
            return url, response.status
    except Exception as e:
        return url, None


async def check_websites(context: ContextTypes.DEFAULT_TYPE):
    urls = get_all_urls()
    if not urls:
        return  # Если нет сайтов, просто выходим

    issues = []
    async with aiohttp.ClientSession() as session:
        tasks = [check_website(session, url) for url in urls]
        results = await asyncio.gather(*tasks)

    for url, status_code in results:
        # Если статус None или не входит в (200, 301, 302), сайт считается недоступным
        if status_code not in (200, 301, 302) or status_code is None:
            issues.append((clean_url(url), status_code))

    # Отправляем сообщение только если есть недоступные сайты
    if issues:
        message = "Некоторые сайты недоступны:\n" + "\n".join(f"{url} (Status: {code})" for url, code in issues)
        chat_ids = get_all_chat_ids()
        for chat_id in chat_ids:
            await context.bot.send_message(chat_id=chat_id, text=message)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_chat_id(chat_id)
    await show_main_menu(update, chat_id)

async def show_main_menu(update: Update, chat_id):
    if chat_id == ADMIN_CHAT_ID:
        keyboard = [
            ["Проверить доступность сайтов"],
            ["Добавить сайт", "Удалить сайт"]
        ]
    else:
        keyboard = [
            ["Проверить доступность сайтов"]
        ]

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.effective_chat.id

    if context.user_data.get('state') == 'WAITING_FOR_URL':
        if text == "Вернуться в меню":
            await show_main_menu(update, chat_id)
            context.user_data['state'] = None
            return

        url = text.strip()
        if is_valid_url(url):
            add_url(url)
            await update.message.reply_text(f"Сайт {url} добавлен в список!")
        else:
            await update.message.reply_text("Пожалуйста, введите корректный URL.")
        
        context.user_data['state'] = None
        await show_main_menu(update, chat_id)
        return

    if text == "Проверить доступность сайтов":
        urls = get_all_urls()
        if not urls:
            await update.message.reply_text("Нет добавленных сайтов для проверки.")
            return
        
        available_sites = []
        unavailable_sites = []
        
        async with aiohttp.ClientSession() as session:
            tasks = [check_website(session, url) for url in urls]
            results = await asyncio.gather(*tasks)

        for url, status_code in results:
            if status_code in (200, 301, 302):
                available_sites.append((clean_url(url), status_code))
            else:
                unavailable_sites.append((clean_url(url), status_code))

        message = ""
        if available_sites:
            message += "Доступные сайты:\n" + "\n".join(f"{url} (Status: {code})" for url, code in available_sites) + "\n"
        else:
            message += "Нет доступных сайтов.\n"

        if unavailable_sites:
            message += "Недоступные сайты:\n" + "\n".join(f"{url} (Status: {code})" for url, code in unavailable_sites)
        else:
            message += "Все сайты доступны!"

        await update.message.reply_text(message)

    elif text == "Добавить сайт":
        if chat_id != ADMIN_CHAT_ID:
            await update.message.reply_text("У вас нет прав для выполнения этого действия.")
            return

        context.user_data['state'] = 'WAITING_FOR_URL'
        
        # Обновляем клавиатуру
        keyboard = [["Вернуться в меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Отправьте URL для добавления (или нажмите 'Вернуться в меню'):", reply_markup=reply_markup)

    elif text == "Удалить сайт":
        if chat_id != ADMIN_CHAT_ID:
            await update.message.reply_text("У вас нет прав для выполнения этого действия.")
            return

        urls = get_all_urls()
        if not urls:
            await update.message.reply_text("Нет добавленных сайтов для удаления.")
            return
        
        keyboard = [[url] for url in urls]
        keyboard.append(["Вернуться в меню"])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Выберите сайт для удаления:", reply_markup=reply_markup)
        context.user_data['state'] = 'WAITING_FOR_DELETE_URL'
        return

    elif context.user_data.get('state') == 'WAITING_FOR_DELETE_URL':
        if text == "Вернуться в меню":
            await show_main_menu(update, chat_id)
            context.user_data['state'] = None
            return
        
        url = text.strip()
        if url in get_all_urls():  # Проверяем, действительно ли URL есть в базе
            delete_url(url)
            await update.message.reply_text(f"Сайт {url} удалён из списка!")
        else:
            await update.message.reply_text("Сайт не найден или неверный URL.")
        
        await show_main_menu(update, chat_id)
        context.user_data['state'] = None
        return

    else:
        await update.message.reply_text("Пожалуйста, выберите действие.")

# Функция для расчета времени до ближайшего интервала 30 минут
def get_time_until_next_half_hour():
    now = datetime.now()
    next_half_hour = now.replace(minute=30 if now.minute < 30 else 0, second=0, microsecond=0)
    if next_half_hour < now:
        next_half_hour += timedelta(hours=1)
    return (next_half_hour - now).seconds

def main():
    create_db()
    create_user_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue
    # Запуск проверки доступности сайтов каждые 30 минут по фиксированному времени
    job_queue.run_repeating(check_websites, interval=1800, first=get_time_until_next_half_hour())

    app.run_polling()

if __name__ == '__main__':
    main()
