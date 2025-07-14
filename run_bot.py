import json
import time
import asyncio
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities


async def log_network_requests(url):
    caps = DesiredCapabilities.CHROME
    caps["goog:loggingPrefs"] = {"performance": "ALL"}

    options = Options()
    options.headless = False
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-javascript")

    driver = uc.Chrome(options=options, desired_capabilities=caps)
    driver.get(url)
    await asyncio.sleep(3)

    # Обновление страницы один раз
    driver.execute_script("location.replace(location.href)")
    await asyncio.sleep(5)

    logs = driver.get_log("performance")
    output_log = []

    for entry in logs:
        message = json.loads(entry["message"])
        msg = message["message"]

        if msg["method"] == "Network.requestWillBeSent":
            req = msg["params"]["request"]
            output_log.append({
                "url": req.get("url"),
                "method": req.get("method"),
                "headers": req.get("headers"),
            })

    with open("network_log.json", "w", encoding="utf-8") as f:
        json.dump(output_log, f, indent=2, ensure_ascii=False)

    driver.quit()
    print(f"✅ Сохранено {len(output_log)} запросов в network_log.json")


if __name__ == "__main__":
    asyncio.run(log_network_requests("https://www.avito.ru/moskva_i_mo/telefony/mobile-ASgBAgICAUSwwQ2I_Dc?cd=1&f=ASgBAQICAUSwwQ2I_DcBQOjrDjT~_dsC_P3bAvr92wI&localPriority=0&q=Apple&s=104&user=1"))
