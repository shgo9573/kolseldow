import sys
import time
import json
import urllib.parse
from pathlib import Path

# --- ייבוא ספריות סלניום ---
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains

# ----------------------------------------------------
# --- הגדרות משתמש - יש לערוך את הערכים הבאים ---
# ----------------------------------------------------
CODE_VALUE = "409573"   # יש להחליף בקוד המוסד שלך
PASSWORD_VALUE = "220106"  # יש להחליף בסיסמה שלך

RUN_HEADLESS = True  # שנה ל-False כדי לראות את הדפדפן פועל מולך (שימושי לבדיקות)

DEFAULT_DOWNLOAD_PATH = str(Path.home() / 'Downloads')
TOPICS_FILE = Path("topics.json")
# ----------------------------------------------------

# --- הגדרות קבועות של האתר ---
LOGIN_URL = "https://www2.kolhalashon.com/#/login/%2FregularSite%2Fnew"
BASE_URL = "https://www2.kolhalashon.com/"

# --- פונקציות עזר לסלניום ---
def create_webdriver() -> webdriver.Remote:
    chrome_options = ChromeOptions()
    if RUN_HEADLESS:
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1400,900")
    prefs = {"download.default_directory": DEFAULT_DOWNLOAD_PATH}
    chrome_options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def wait_visible(driver: webdriver.Remote, by: By, selector: str, timeout: int = 10):
    return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((by, selector)))

def wait_clickable(driver: webdriver.Remote, by: By, selector: str, timeout: int = 10):
    return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector)))

def js_click(driver: webdriver.Remote, element):
    driver.execute_script("arguments[0].click();", element)

# --- פונקציות ליבה ---
def perform_login(driver: webdriver.Remote):
    print("מתחיל תהליך התחברות...")
    print("טוען את דף ההתחברות...")
    driver.get(LOGIN_URL)

    try:
        wait_visible(driver, By.CSS_SELECTOR, "input[formcontrolname='code']").send_keys(CODE_VALUE)
        password_input = wait_visible(driver, By.CSS_SELECTOR, "input[formcontrolname='password']")
        password_input.send_keys(PASSWORD_VALUE)
        password_input.send_keys(Keys.ENTER)
        wait_visible(driver, By.CSS_SELECTOR, ".banner-search input, .banner-title input", timeout=25)
        print("✅ התחברות בוצעה בהצלחה.")
        return True
    except TimeoutException:
        print("❌ שגיאה: התחברות נכשלה.")
        return False

def handle_search_results(driver: webdriver.Remote) -> bool:
    try:
        WebDriverWait(driver, 15).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "app-shiurim-display .shiur-container")),
                EC.presence_of_element_located((By.CSS_SELECTOR, ".rav-container"))
            )
        )
        rav_results = driver.find_elements(By.CSS_SELECTOR, ".rav-container")
        if rav_results:
            print("\nנמצאו מספר רבנים תואמים:")
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.find_element(By.CSS_SELECTOR, ".rav-container .rav-name").text.strip() != ""
                )
            except TimeoutException:
                print("אזהרה: המתנה לטעינת שמות הרבנים נכשלה.")

            rav_results = driver.find_elements(By.CSS_SELECTOR, ".rav-container")
            rav_display_list = []
            for rav_element in rav_results:
                name = rav_element.find_element(By.CSS_SELECTOR, ".rav-name").text.strip()
                try:
                    shiurim_count = rav_element.find_element(By.CSS_SELECTOR, ".rav-shiurim-sum").text.strip()
                except NoSuchElementException:
                    shiurim_count = ""
                rav_display_list.append(f"{name} ({shiurim_count})")

            for i, display_text in enumerate(rav_display_list):
                 print(f"[{i + 1}] {display_text}")
            
            while True:
                try:
                    choice = int(input(f"בחר את הרב הרצוי (1-{len(rav_display_list)}): "))
                    if 1 <= choice <= len(rav_display_list):
                        fresh_rav_results = driver.find_elements(By.CSS_SELECTOR, ".rav-container")
                        link_to_click = fresh_rav_results[choice - 1].find_element(By.CSS_SELECTOR, "a.rav-name")
                        js_click(driver, link_to_click)
                        break
                    else:
                        print("בחירה לא חוקית.")
                except (ValueError, IndexError):
                    print("קלט לא חוקי.")
            
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "app-shiurim-display .shiur-container")))
        print("✅ הגעה לדף השיעורים.")
        return True
    except TimeoutException:
        print("❌ לא נטענו תוצאות חיפוש.")
        return False

def perform_search(driver: webdriver.Remote, query: str) -> bool:
    print(f"מבצע חיפוש עבור: '{query}'...")
    try:
        if query.strip().startswith("הרב"):
            print("זוהה חיפוש רב. משתמש בנתיב חיפוש רבנים.")
            search_type_path = "ravSearch"
        else:
            print("מבצע חיפוש שיעורים כללי.")
            search_type_path = "searchResults"

        encoded_query = urllib.parse.quote(query)
        new_hash = f"#/regularSite/{search_type_path}/{encoded_query}"
        print(f"מנווט ל: {new_hash}")
        driver.execute_script(f"window.location.hash = '{new_hash}';")
        
        print("ממתין לתוצאות...")
        return handle_search_results(driver)
    except Exception as e:
        print(f"❌ שגיאה במהלך החיפוש הישיר: {e}")
        return False

def navigate_by_topic(driver: webdriver.Remote) -> bool:
    if not TOPICS_FILE.exists():
        print(f"קובץ הנושאים '{TOPICS_FILE}' לא קיים. יש ליצור אותו באמצעות הסקריפט הנפרד 'create_topics_file.py'.")
        return False
    with open(TOPICS_FILE, 'r', encoding='utf-8') as f:
        topics = json.load(f)
    main_categories = list(topics.keys())
    print("\n--- בחירת קטגוריה ראשית ---")
    for i, cat in enumerate(main_categories):
        print(f"[{i+1}] {cat}")
    while True:
        try:
            choice = int(input(f"בחר קטגוריה (1-{len(main_categories)}): ")) - 1
            if 0 <= choice < len(main_categories):
                selected_main_cat = main_categories[choice]
                break
            else:
                print("בחירה לא חוקית.")
        except ValueError:
            print("יש להזין מספר.")
    sub_categories = topics[selected_main_cat]
    if not sub_categories:
        print("לקטגוריה זו אין תתי-נושאים לבחירה.")
        return False
    print(f"\n--- בחירת תת-נושא עבור '{selected_main_cat}' ---")
    for i, sub_cat in enumerate(sub_categories):
        print(f"[{i+1}] {sub_cat['name']}")
    while True:
        try:
            choice = int(input(f"בחר תת-נושא (1-{len(sub_categories)}): ")) - 1
            if 0 <= choice < len(sub_categories):
                selected_sub_cat = sub_categories[choice]
                break
            else:
                print("בחירה לא חוקית.")
        except ValueError:
            print("יש להזין מספר.")
    print(f"מנווט אל: {selected_sub_cat['name']}...")
    driver.get(selected_sub_cat['href'])
    return handle_search_results(driver)

def display_current_shiurim(driver: webdriver.Remote) -> list:
    print("\n--- רשימת שיעורים ---")
    try:
        shiur_elements = driver.find_elements(By.CSS_SELECTOR, "app-shiurim-display .shiur-container")
        if not shiur_elements:
            print("לא נמצאו שיעורים בתצוגה הנוכחית.")
            return []
        for i, shiur_element in enumerate(shiur_elements):
            title = shiur_element.find_element(By.CSS_SELECTOR, ".shiurim-title").text
            rav = shiur_element.find_element(By.CSS_SELECTOR, ".shiurim-rav-name").text
            date = shiur_element.find_element(By.CSS_SELECTOR, ".shiurim-start-time").text
            print(f"[{i + 1}] {title} - {rav} ({date})")
        return shiur_elements
    except NoSuchElementException:
        print("שגיאה בקריאת פרטי השיעורים.")
        return []

def display_and_select_filter(driver: webdriver.Remote) -> bool:
    print("\n--- סינון לפי קטגוריה ---")
    try:
        try:
            rav_filter_input = driver.find_element(By.XPATH, "//input[@placeholder='חיפוש רב']")
            filter_prompt = input("האם תרצה לסנן את רשימת הרבנים לפני הצגתה? (כ/ל): ").lower()
            if filter_prompt == 'כ':
                query = input("הזן שם רב לסינון הרשימה: ")
                rav_filter_input.clear()
                rav_filter_input.send_keys(query)
                print("ממתין לעדכון רשימת המסננים...")
                time.sleep(3)
        except NoSuchElementException:
            print("לא נמצאה תיבת חיפוש מסננים, מציג את כל האפשרויות.")
        
        filter_groups = driver.find_elements(By.CSS_SELECTOR, "app-filter-container")
        if not filter_groups:
            print("לא נמצאו קטגוריות סינון.")
            return False

        all_filters = []
        print("סורק את כל אפשרויות הסינון הזמינות...")

        for group in filter_groups:
            try:
                header = group.find_element(By.CSS_SELECTOR, ".filter-header")
                category_title = header.text.strip()
                if not category_title: continue

                inner_container = group.find_element(By.CSS_SELECTOR, ".filter-container")
                if "opened" not in inner_container.get_attribute("class"):
                    js_click(driver, header)
                    time.sleep(0.5)

                while True:
                    try:
                        show_more_button = group.find_element(By.XPATH, ".//div[contains(@class, 'display-more') and contains(normalize-space(), 'הצג עוד')]")
                        js_click(driver, show_more_button)
                        time.sleep(0.5)
                    except NoSuchElementException:
                        break
                
                options = group.find_elements(By.CSS_SELECTOR, "mat-checkbox.filter-option")
                if options:
                    print(f"\n--- {category_title} ---")
                    for option in options:
                        try:
                            label_element = option.find_element(By.CSS_SELECTOR, ".mat-checkbox-label")
                            full_label_text = driver.execute_script("return arguments[0].textContent;", label_element).strip().replace('\n', ' ').replace('  ', ' ')
                            if full_label_text:
                                print(f"[{len(all_filters) + 1}] {full_label_text}")
                                all_filters.append({'text': full_label_text, 'element': option})
                        except NoSuchElementException: continue
            except Exception: continue
        
        if not all_filters:
            print("לא נמצאו אפשרויות סינון זמינות.")
            return False

        while True:
            try:
                choice = int(input(f"\nבחר מספר מסנן ליישום (1-{len(all_filters)}): "))
                if 1 <= choice <= len(all_filters):
                    selected_filter = all_filters[choice - 1]
                    
                    print(f"מפעיל סינון: {selected_filter['text']}...")
                    old_shiurim_container = driver.find_element(By.CSS_SELECTOR, "app-shiurim-display")
                    js_click(driver, selected_filter['element'])
                    
                    print("ממתין לרענון התוצאות...")
                    WebDriverWait(driver, 15).until(EC.staleness_of(old_shiurim_container))
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "app-shiurim-display")))
                    print("✅ תוצאות סוננו בהצלחה.")
                    return True
                else:
                    print("בחירה לא חוקית.")
            except (ValueError, IndexError):
                print("קלט לא חוקי. יש להזין מספר מהרשימה.")

    except Exception as e:
        print(f"❌ אירעה שגיאה בטיפול במסננים: {e}")
        return False

def download_selected_shiur(driver: webdriver.Remote, elements: list):
    if not elements: return
    while True:
        try:
            choice = int(input(f"\nבחר מספר שיעור להורדה (1-{len(elements)}): "))
            if 1 <= choice <= len(elements):
                selected_shiur = elements[choice - 1]
                download_button = selected_shiur.find_element(By.XPATH, ".//button[contains(@class, 'click-option-button') and .//svg-icon[contains(@src, 'download-i.svg')]]")
                js_click(driver, download_button)
                try:
                    audio_option = wait_visible(driver, By.XPATH, "//div[contains(@class, 'download-option') and .//svg-icon[contains(@src, 'download-i.svg')]]", timeout=5)
                    js_click(driver, audio_option)
                except TimeoutException:
                    pass
                print(f"✅ ההורדה אמורה להתחיל. הקובץ יישמר בתיקייה: {DEFAULT_DOWNLOAD_PATH}")
                time.sleep(20)
                break
            else:
                print("בחירה לא חוקית.")
        except (ValueError, IndexError):
            print("קלט לא חוקי.")

def interact_with_results_page(driver: webdriver.Remote):
    while True:
        shiur_elements = display_current_shiurim(driver)
        
        print("\n--- אפשרויות ---")
        print("[ה]ורדת שיעור")
        print("[ס]ינון לפי קטגוריה")
        print("[ע]מוד הבא")
        print("[ח]זרה לתפריט הראשי")
        action = input("מה תרצה לעשות? ").lower()
        
        if action == 'ה':
            download_selected_shiur(driver, shiur_elements)
            break
        elif action == 'ס':
            display_and_select_filter(driver)
        elif action == 'ע':
            try:
                next_button = driver.find_element(By.CSS_SELECTOR, "app-pagination-options .next:not(.disabled)")
                js_click(driver, next_button)
                print("עובר לעמוד הבא...")
                time.sleep(4)
            except NoSuchElementException:
                print("אין עמוד הבא, או שכפתור הניווט לא נמצא.")
        elif action == 'חזרה':
            break
        else:
            print("אפשרות לא ידועה.")

def main():
    driver = None
    try:
        while True:
            print("\n--- תפריט ראשי ---")
            print("[1] חיפוש לפי שם רב או שיעור")
            print("[2] בחירה מתוך רשימת נושאים")
            print("[3] יציאה")
            main_choice = input("אנא בחר אפשרות: ")
            if main_choice in ['1', '2']:
                if not driver:
                    driver = create_webdriver()
                    if not perform_login(driver):
                        if driver: driver.quit(); driver = None
                        continue
            if main_choice == '1':
                query = input("הזן את שם הרב או השיעור לחיפוש: ")
                if perform_search(driver, query):
                    interact_with_results_page(driver)
            elif main_choice == '2':
                if navigate_by_topic(driver):
                    interact_with_results_page(driver)
            elif main_choice == '3':
                break
            else:
                print("בחירה לא חוקית, אנא נסה שוב.")
    finally:
        if driver:
            print("\nהתהליך הסתיים. סוגר את הדפדפן.")
            driver.quit()

if __name__ == "__main__":
    main()