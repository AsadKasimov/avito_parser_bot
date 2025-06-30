import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

def save_page_html(link, headless=True):
    options = Options()
    options.headless = False
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=ru-RU")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")

    driver = uc.Chrome(options=options)
    try:
        driver.get(link)
        # Ждать полной загрузки страницы (можно увеличить)
        WebDriverWait(driver, 20).until(lambda d: d.execute_script('return document.readyState') == 'complete')
        import time; time.sleep(5)  # Просто для надёжности, можешь увеличить
        html = driver.page_source
        with open("avito_full_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("✅ Страница сохранена как avito_full_page.html")
    finally:
        driver.quit()

if __name__ == "__main__":
    link = "https://www.avito.ru/moskva_i_mo/telefony/mobile-ASgBAgICAUSwwQ2I_Dc?cd=1&f=ASgBAQECAUSwwQ2I_DcBQOjrDkT~_dsC_P3bAvr92wL4_dsCAUXGmgwZeyJmcm9tIjoxMDAwMCwidG8iOjMwMDAwfQ&q=Apple&s=104&user=1"
    save_page_html(link, headless=False)
