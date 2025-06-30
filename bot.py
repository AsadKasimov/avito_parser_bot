import logging
import asyncio
import sqlite3
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from avito_selenium_parser import monitor_link_selenium

BOT_TOKEN = 'БОТ_код'
DATABASE = 'subscriptions.db'

MENU_BUTTONS = [
    ["Список ссылок", "Очистить все"],
    ["Удалить ссылку", "Старт мониторинга", "Стоп мониторинга"],
    ["Помощь"]
]
markup = ReplyKeyboardMarkup(MENU_BUTTONS, resize_keyboard=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            url TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            chat_id INTEGER,
            url TEXT,
            ad_id TEXT,
            PRIMARY KEY(chat_id, url, ad_id)
        )
    """)
    conn.commit()
    conn.close()

def add_link(chat_id, url):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM subscriptions WHERE chat_id=? AND url=?", (chat_id, url))
    if c.fetchone():
        conn.close()
        return False
    c.execute("INSERT INTO subscriptions (chat_id, url) VALUES (?, ?)", (chat_id, url))
    conn.commit()
    conn.close()
    return True

def remove_link(chat_id, idx):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, url FROM subscriptions WHERE chat_id=? ORDER BY id", (chat_id,))
    rows = c.fetchall()
    if 0 <= idx < len(rows):
        sub_id = rows[idx][0]
        url = rows[idx][1]
        c.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))
        c.execute("DELETE FROM seen WHERE chat_id=? AND url=?", (chat_id, url))
        conn.commit()
        conn.close()
        return url
    conn.close()
    return None

def clear_links(chat_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM subscriptions WHERE chat_id=?", (chat_id,))
    c.execute("DELETE FROM seen WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()

def get_links(chat_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT url FROM subscriptions WHERE chat_id=?", (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

# Для отслеживания активных задач мониторинга
active_tasks = {}

def is_allowed(url):
    if "/audio_i_video/" in url or "/predlozheniya_uslug/" in url:
        return False
    return url.startswith("http://") or url.startswith("https://")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пришли ссылку Avito для мониторинга или выбери действие на клавиатуре:",
        reply_markup=markup
    )

async def add_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    chat_id = update.effective_chat.id
    if not is_allowed(url):
        await update.message.reply_text("Ссылка не поддерживается или из запрещённого раздела.")
        return
    ok = add_link(chat_id, url)
    if ok:
        await update.message.reply_text("Ссылка добавлена!\nНажмите 'Старт мониторинга' для мгновенного запуска браузера.")
    else:
        await update.message.reply_text("Такая ссылка уже есть.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    links = get_links(chat_id)
    if not links:
        await update.message.reply_text("Список пуст.")
    else:
        reply = "\n".join([f"{i+1}. {url}" for i, url in enumerate(links)])
        await update.message.reply_text("Ваши ссылки:\n" + reply)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_links(update.effective_chat.id)
    await update.message.reply_text("Все ссылки удалены.")

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        idx = int(context.args[0]) - 1
    except (IndexError, ValueError):
        await update.message.reply_text("Используй: /remove <номер из /list>")
        return
    url = remove_link(update.effective_chat.id, idx)
    if url:
        await update.message.reply_text(f"Удалено: {url}")
    else:
        await update.message.reply_text("Не могу найти такую ссылку.")

async def keyboard_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    chat_id = update.effective_chat.id
    if text == "список ссылок":
        await list_command(update, context)
    elif text == "очистить все":
        await clear_command(update, context)
    elif text == "удалить ссылку":
        await update.message.reply_text("Для удаления — напиши: /remove <номер>")
    elif text == "помощь":
        await update.message.reply_text(
            "Команды:\n"
            "/list — список ссылок\n"
            "/remove <номер> — удалить ссылку\n"
            "/clear — удалить все\n"
            "Или пришли Avito-ссылку для мониторинга.\n"
            "Нажми 'Старт мониторинга' чтобы запустить."
        )
    elif text == "старт мониторинга":
        links = get_links(chat_id)
        if not links:
            await update.message.reply_text("Сначала добавь хотя бы одну ссылку!")
            return
        # Запустить мониторинг по всем ссылкам пользователя
        started = 0
        for url in links:
            key = (chat_id, url)
            if key in active_tasks and not active_tasks[key].done():
                continue  # уже мониторится
            active_tasks[key] = asyncio.create_task(
                monitor_link_selenium(chat_id, url, context.application)
            )
            started += 1
        if started:
            await update.message.reply_text("Мониторинг запущен для всех ссылок!")
        else:
            await update.message.reply_text("Мониторинг уже идёт.")
    elif text == "стоп мониторинга":
        stopped = 0
        to_cancel = []
        for key, task in list(active_tasks.items()):
            chat_id_, url_ = key
            if chat_id_ == chat_id and not task.done():
                task.cancel()
                stopped += 1
                to_cancel.append(key)
        for key in to_cancel:
            del active_tasks[key]
        if stopped:
            await update.message.reply_text("Мониторинг остановлен для всех ссылок.")
        else:
            await update.message.reply_text("Нет активного мониторинга.")
    else:
        await add_link_handler(update, context)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyboard_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
