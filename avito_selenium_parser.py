import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import sqlite3
import asyncio

DATABASE = 'subscriptions.db'
MONITOR_INTERVAL = 30

def get_seen(chat_id, url):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT ad_id FROM seen WHERE chat_id=? AND url=?", (chat_id, url))
    seen = set(row[0] for row in c.fetchall())
    conn.close()
    return seen

def save_seen(chat_id, url, ad_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO seen (chat_id, url, ad_id) VALUES (?, ?, ?)", (chat_id, url, ad_id))
    conn.commit()
    conn.close()

async def monitor_link_selenium(chat_id, url, app):
    options = Options()
    options.headless = False
    options.add_argument("--window-size=1920,1080")
    options.page_load_strategy = 'eager'  # Важно!
    driver = uc.Chrome(options=options)
    try:
        driver.get(url)
        await asyncio.sleep(1.7)  # только чтобы сайт показал DOM!
        seen = get_seen(chat_id, url)
        while True:
            # Быстро 3-5 раз прокручиваем, чтобы точно подгрузились все объявления
            for _ in range(5):
                driver.execute_script("window.scrollBy(0, window.innerHeight);")
                await asyncio.sleep(0.3)
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            count = 0
            for card in soup.select('[data-marker="item"]'):
                # Игнорировать из "Подобрали для вас"
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
                seen.add(item_id)
                save_seen(chat_id, url, item_id)
                title = title_elem.text.strip()
                price = price_elem['content'] if price_elem.has_attr('content') else price_elem.text
                url_full = 'https://www.avito.ru' + link_elem['href']
                if '/audio_i_video/' in url_full or '/predlozheniya_uslug/' in url_full:
                    continue
                await app.bot.send_message(chat_id, f"🆕 {title}\n💰 {price} ₽\n🔗 {url_full}")
                count += 1
            await asyncio.sleep(MONITOR_INTERVAL)
            driver.refresh()
    except asyncio.CancelledError:
        driver.quit()
        return
    except Exception as e:
        await app.bot.send_message(chat_id, f"Ошибка: {e}")
        driver.quit()
    driver.quit()
