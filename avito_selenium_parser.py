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
from selenium.webdriver.common.keys import Keys
import pyautogui
import pyperclip
import keyboard
import psutil

DATABASE = 'subscriptions.db'
MONITOR_INTERVAL = 5
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
    c.execute("DELETE FROM seen WHERE chat_id=? AND ad_id NOT IN (SELECT ad_id FROM seen WHERE chat_id=? ORDER BY added_at DESC LIMIT ?)",
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

async def scroll_page(driver, times=4, delay=0.8):
    print("🔃 Скроллинг страницы...")
    for _ in range(times):
        driver.execute_script("window.scrollBy(0, window.innerHeight);")
        await asyncio.sleep(delay)

async def parse_page(driver, chat_id, app):
    print("👁 Парсинг страницы...")
    seen = get_seen(chat_id)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    print("🔢 Кол-во элементов:", len(soup.select('[data-marker="item"]')))
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
        print(f"🆕 {title} | {price}")
        await app.bot.send_message(chat_id, f"\U0001f195 {title}\n\U0001f4b0 {price} ₽\n\U0001f517 {url_full}")

async def monitor_link_selenium(chat_id, url, app):
    print("🚀 Запуск мониторинга...")
    await app.bot.send_message(chat_id, "🚀 Мониторинг запущен!")

    options = Options()
    options.headless = False
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.page_load_strategy = 'eager'

    driver = uc.Chrome(options=options, version_main=138)
    await asyncio.sleep(2)

    screen_width, screen_height = driver.execute_script("return [screen.availWidth, screen.availHeight];")
    driver.execute_cdp_cmd("Browser.setWindowBounds", {
        "windowId": driver.window_handles.index(driver.current_window_handle),
        "bounds": {
            "left": 0,
            "top": 0,
            "width": screen_width,
            "height": screen_height,
            "windowState": "fullscreen"
        }
    })

    driver.get(url)
    await asyncio.sleep(2)

    if os.path.exists(COOKIES_FILE):
        await asyncio.sleep(1)
        with open(COOKIES_FILE, "rb") as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                try:
                    driver.add_cookie(cookie)
                except Exception:
                    pass
        driver.refresh()
        await asyncio.sleep(2)

    app.bot_data[(chat_id, url)] = driver

    def save_cookies():
        cookies = driver.get_cookies()
        with open(COOKIES_FILE, "wb") as f:
            pickle.dump(cookies, f)

    try:
        while True:
            print("♻️ Новый цикл проверки...")
            html = driver.page_source
            if "Доступ ограничен" in html or "Продолжить" in html and "капча" in html:
                await app.bot.send_message(chat_id, "⚠️ КАПЧА! Пробую обойти...")
                pyperclip.copy(url)
                time.sleep(1)
                pyautogui.click(900, 90)
                time.sleep(1)
                keyboard.press_and_release('ctrl+v')
                time.sleep(0.5)
                keyboard.press_and_release('enter')
                await app.bot.send_message(chat_id, "🔁 Ссылка повторно открыта вручную. Жду 10 секунд...")
                time.sleep(10)
                save_cookies()
                driver.refresh()
                await asyncio.sleep(2)
                continue

            scroll_task = asyncio.create_task(scroll_page(driver))
            parse_task = asyncio.create_task(parse_page(driver, chat_id, app))
            await asyncio.gather(scroll_task, parse_task)

            await asyncio.sleep(MONITOR_INTERVAL)
            driver.refresh()
    finally:
        driver.quit()
        app.bot_data.pop((chat_id, url), None)

        for proc in psutil.process_iter(['name']):
            if proc.info['name'] in ('chrome.exe', 'chromedriver.exe'):
                try:
                    proc.kill()
                except Exception:
                    pass
