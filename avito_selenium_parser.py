import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import sqlite3
import asyncio
import time
import os
import pickle
import random

DATABASE = 'subscriptions.db'
MONITOR_INTERVAL = 5
SEEN_LIMIT = 1000
COOKIES_FILE = "avito_cookies.pkl"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

drivers = {}  # chat_id -> driver


def get_seen(chat_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT ad_id FROM seen WHERE chat_id=? ORDER BY rowid DESC LIMIT ?", (chat_id, SEEN_LIMIT))
    seen = set(row[0] for row in c.fetchall())
    conn.close()
    return seen


def save_seen_bulk(chat_id, new_ids):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    now = int(time.time())
    c.executemany("INSERT OR IGNORE INTO seen (chat_id, ad_id, added_at) VALUES (?, ?, ?)",
                  [(chat_id, ad_id, now) for ad_id in new_ids])
    c.execute(
        "DELETE FROM seen WHERE chat_id=? AND ad_id NOT IN (SELECT ad_id FROM seen WHERE chat_id=? ORDER BY added_at DESC LIMIT ?)",
        (chat_id, chat_id, SEEN_LIMIT))
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


def get_or_create_driver(chat_id):
    if chat_id in drivers:
        return drivers[chat_id]
    options = Options()
    options.headless = False
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f'user-agent={USER_AGENT}')
    options.page_load_strategy = 'eager'
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-javascript')
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.javascript": 2
    }
    options.add_experimental_option("prefs", prefs)
    driver = uc.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    drivers[chat_id] = driver
    return driver


async def monitor_link_selenium(chat_id, url, app):
    driver = get_or_create_driver(chat_id)

    try:
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
        await asyncio.sleep(random.uniform(1.5, 2.0))

        def save_cookies():
            cookies = driver.get_cookies()
            with open(COOKIES_FILE, "wb") as f:
                pickle.dump(cookies, f)

        while True:
            html = driver.page_source
            if "Доступ ограничен" in html or ("Продолжить" in html and "капча" in html):
                await app.bot.send_message(chat_id, "⚠️ КАПЧА! Открой браузер, реши капчу, затем отправь /continue.")
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
                continue

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            await asyncio.sleep(1.0)

            try:
                cards_data = driver.execute_script("""
                return Array.from(document.querySelectorAll('[data-marker="item"]')).map(el => {
                  return {
                    id: el.getAttribute('data-item-id'),
                    title: el.querySelector('[itemprop="name"]')?.innerText,
                    price: el.querySelector('[itemprop="price"]')?.getAttribute('content') || el.querySelector('[itemprop="price"]')?.innerText,
                    link: el.querySelector('a[itemprop="url"]')?.getAttribute('href')
                  };
                });
                """)
            except Exception as e:
                await app.bot.send_message(chat_id, f"Ошибка при извлечении данных объявлений: {e}")
                await asyncio.sleep(random.uniform(2, 3))
                continue

            seen = get_seen(chat_id)
            new_ids = set()

            async def parse_and_notify():
                for card in cards_data:
                    item_id = card['id']
                    if not item_id or item_id in seen:
                        continue
                    title = card['title']
                    price = card['price']
                    link = card['link']
                    if not title or not price or not link:
                        continue
                    url_full = 'https://www.avito.ru' + link
                    if "iphone" not in url_full.lower():
                        continue
                    new_ids.add(item_id)
                    await app.bot.send_message(chat_id, f"🆕 {title}\n💰 {price} ₽\n🔗 {url_full}")

            await parse_and_notify()
            save_seen_bulk(chat_id, new_ids)

            await asyncio.sleep(random.uniform(3, 5))
            driver.execute_script("location.replace(location.href)")

    except asyncio.CancelledError:
        pass
    except Exception as e:
        await app.bot.send_message(chat_id, f"❗ Ошибка мониторинга: {e}")
    finally:
        if chat_id in drivers:
            try:
                drivers[chat_id].quit()
            except Exception:
                pass
            del drivers[chat_id]
