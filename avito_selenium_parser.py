import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import sqlite3
import asyncio
import time
import os
import pickle
import random

DATABASE = 'subscriptions.db'
MONITOR_INTERVAL = 5  # строго по требованиям
SEEN_LIMIT = 1000
COOKIES_FILE = "avito_cookies.pkl"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

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

async def monitor_link_selenium(chat_id, url, app):
    options = Options()
    options.headless = False
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f'user-agent={USER_AGENT}')
    options.page_load_strategy = 'eager'

    driver = uc.Chrome(options=options)

    if os.path.exists(COOKIES_FILE):
        driver.get("https://www.avito.ru/")
        await asyncio.sleep(2)
        with open(COOKIES_FILE, "rb") as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                try:
                    driver.add_cookie(cookie)
                except Exception:
                    pass

    driver.get(url)
    await asyncio.sleep(random.uniform(1.5, 2.5))

    def save_cookies():
        cookies = driver.get_cookies()
        with open(COOKIES_FILE, "wb") as f:
            pickle.dump(cookies, f)

    while True:
        html = driver.page_source
        if "Доступ ограничен" in html or ("Продолжить" in html and "капча" in html):
            await app.bot.send_message(chat_id, "⚠️ КАПЧА! Открой браузер, реши капчу, затем отправь /continue.")
            print("Ждём прохождения капчи...")
            solved = False
            while not solved:
                await asyncio.sleep(3)
                updates = await app.bot.get_updates()
                for upd in updates:
                    if upd.message and upd.message.text and upd.message.text.lower() == "/continue":
                        solved = True
                        break
            save_cookies()
            await app.bot.send_message(chat_id, "Продолжаю работу!")
            driver.refresh()
            await asyncio.sleep(2)
            continue

        for _ in range(random.randint(2, 5)):
            driver.execute_script("window.scrollBy(0, window.innerHeight);")
            await asyncio.sleep(random.uniform(0.6, 1.2))

        try:
            WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-marker="item"]')))
        except Exception:
            await app.bot.send_message(chat_id, "Ошибка загрузки страницы!")
            await asyncio.sleep(MONITOR_INTERVAL)
            continue

        seen = get_seen(chat_id)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        for card in soup.select('[data-marker="item"]'):
            parent = card
            skip = False
            while parent:
                if parent.has_attr("data-marker") and parent["data-marker"] == "itemsCarousel":
                    skip = True
                    break
                parent = parent.parent
            if skip:
                continue

            link_elem = card.select_one('a[itemprop="url"]')
            title_elem = card.select_one('[itemprop="name"]')
            price_elem = card.select_one('[itemprop="price"]')
            if not (title_elem and link_elem and price_elem):
                continue
            item_id = card.get('data-item-id') or link_elem['href'].split('_')[-1].split('?')[0]
            if item_id in seen:
                continue
            save_seen(chat_id, item_id)
            title = title_elem.text.strip()
            price = price_elem['content'] if price_elem.has_attr('content') else price_elem.text
            url_full = 'https://www.avito.ru' + link_elem['href']
            if '/audio_i_video/' in url_full or '/predlozheniya_uslug/' in url_full:
                continue
            await app.bot.send_message(chat_id, f"🆕 {title}\n💰 {price} ₽\n🔗 {url_full}")
        await asyncio.sleep(MONITOR_INTERVAL)
        driver.refresh()

    driver.quit()
