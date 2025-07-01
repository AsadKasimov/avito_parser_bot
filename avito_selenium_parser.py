import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import sqlite3
import asyncio
import time

DATABASE = 'subscriptions.db'
MONITOR_INTERVAL = 30
SEEN_LIMIT = 1000


def get_seen(chat_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT ad_id FROM seen WHERE chat_id=? ORDER BY added_at DESC LIMIT ?", (chat_id, SEEN_LIMIT))
    seen = set(row[0] for row in c.fetchall())
    conn.close()
    return seen


def save_seen(chat_id, ad_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    now = int(time.time())
    c.execute("INSERT OR IGNORE INTO seen (chat_id, ad_id, added_at) VALUES (?, ?, ?)", (chat_id, ad_id, now))
    # Удалить старые id если больше лимита
    c.execute("SELECT ad_id FROM seen WHERE chat_id=? ORDER BY added_at DESC", (chat_id,))
    rows = c.fetchall()
    if len(rows) > SEEN_LIMIT:
        ids_to_delete = [row[0] for row in rows[SEEN_LIMIT:]]
        c.executemany("DELETE FROM seen WHERE chat_id=? AND ad_id=?", [(chat_id, ad_id) for ad_id in ids_to_delete])
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
    options.page_load_strategy = 'eager'
    driver = uc.Chrome(options=options)
    try:
        driver.get(url)
        await asyncio.sleep(2)
        while True:
            for _ in range(5):
                driver.execute_script("window.scrollBy(0, window.innerHeight);")
                await asyncio.sleep(0.8)
            try:
                WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '[data-marker="item"]')))
            except Exception:
                await app.bot.send_message(chat_id, "Ошибка загрузки страницы!")
                await asyncio.sleep(MONITOR_INTERVAL)
                continue

            seen = get_seen(chat_id)
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            for card in soup.select('[data-marker="item"]'):
                # Пропустить карусель "Подобрали для вас"
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
                if not (title_elem and link_elem and price_elem): continue
                item_id = card.get('data-item-id') or link_elem['href'].split('_')[-1].split('?')[0]
                if item_id in seen: continue
                save_seen(chat_id, item_id)
                title = title_elem.text.strip()
                price = price_elem['content'] if price_elem.has_attr('content') else price_elem.text
                url_full = 'https://www.avito.ru' + link_elem['href']
                if '/audio_i_video/' in url_full or '/predlozheniya_uslug/' in url_full:
                    continue
                await app.bot.send_message(chat_id, f"🆕 {title}\n💰 {price} ₽\n🔗 {url_full}")
            await asyncio.sleep(MONITOR_INTERVAL)
            driver.refresh()
    except asyncio.CancelledError:
        driver.quit()
        return
    except Exception as e:
        await app.bot.send_message(chat_id, f"Ошибка: {e}")
        driver.quit()
    driver.quit()
