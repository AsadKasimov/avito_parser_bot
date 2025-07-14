import requests
from bs4 import BeautifulSoup
import sqlite3
import asyncio
import time
import os
import random

DATABASE = 'subscriptions.db'
MONITOR_INTERVAL = 5
SEEN_LIMIT = 1000
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

HEADERS = {
    "User-Agent": USER_AGENT
}

def get_seen(chat_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT ad_id FROM seen WHERE chat_id=? ORDER BY rowid DESC LIMIT ?", (chat_id, SEEN_LIMIT))
    seen = set(row[0] for row in c.fetchall())
    conn.close()
    return seen

def save_seen(chat_id, ad_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    now = int(time.time())
    c.execute("INSERT OR IGNORE INTO seen (chat_id, ad_id, added_at) VALUES (?, ?, ?)", (chat_id, ad_id, now))
    c.execute("DELETE FROM seen WHERE chat_id=? AND ad_id NOT IN (SELECT ad_id FROM seen WHERE chat_id=? ORDER BY added_at DESC LIMIT ?)", (chat_id, chat_id, SEEN_LIMIT))
    conn.commit()
    conn.close()

def clear_seen(chat_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM seen WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()

def init_db_seen():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            chat_id INTEGER,
            ad_id TEXT,
            added_at INTEGER,
            PRIMARY KEY (chat_id, ad_id)
        )
    """)
    conn.commit()
    conn.close()

async def monitor_link_parser(chat_id, url, app):
    while True:
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                await app.bot.send_message(chat_id, f"Ошибка загрузки страницы: {response.status_code}")
                await asyncio.sleep(MONITOR_INTERVAL)
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            seen = get_seen(chat_id)
            for card in soup.select('[data-marker="item"]'):
                link_elem = card.select_one('a[itemprop="url"]')
                title_elem = card.select_one('[itemprop="name"]')
                price_elem = card.select_one('[itemprop="price"]')
                if not (title_elem and link_elem and price_elem):
                    continue
                item_id = card.get('data-item-id') or link_elem['href'].split('_')[-1].split('?')[0]
                if item_id in seen:
                    continue
                url_full = 'https://www.avito.ru' + link_elem['href']
                if "iphone" not in url_full.lower():
                    continue
                save_seen(chat_id, item_id)
                title = title_elem.text.strip()
                price = price_elem['content'] if price_elem.has_attr('content') else price_elem.text.strip()
                await app.bot.send_message(chat_id, f"🆕 {title}\n💰 {price} ₽\n🔗 {url_full}")

        except Exception as e:
            await app.bot.send_message(chat_id, f"Ошибка: {str(e)}")

        await asyncio.sleep(MONITOR_INTERVAL)
