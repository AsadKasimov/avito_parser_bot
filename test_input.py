import time
import pyautogui
import pyperclip
import keyboard
from selenium import webdriver

# Скопировать ссылку в буфер обмена
avito_url = "https://www.avito.ru/all/bytovaya_elektronika?q=ноутбук"
pyperclip.copy(avito_url)

# Запустить Chrome и открыть Avito
driver = webdriver.Chrome()
driver.get("https://www.avito.ru")
driver.maximize_window()
time.sleep(4)

# Координаты адресной строки
address_bar_x, address_bar_y = 900, 90

# Клик по адресной строке
pyautogui.click(address_bar_x, address_bar_y)
time.sleep(1)

# Используем keyboard вместо pyautogui
keyboard.press_and_release('ctrl+v')
time.sleep(0.5)

# Нажимаем Enter
keyboard.press_and_release('enter')
print("✅ Ссылка вставлена и нажато Enter")

# Ждём загрузку
time.sleep(10)
driver.quit()
