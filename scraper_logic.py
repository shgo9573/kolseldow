# scraper_logic.py
import time
import json
import urllib.parse
from pathlib import Path
import logging
import configparser
import os
from tkinter import filedialog
import tkinter as tk
import shutil

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

# --- הגדרות משתמש ---
CODE_VALUE = "409573"
PASSWORD_VALUE = "220106"
RUN_HEADLESS = True
TOPICS_FILE = Path("topics.json")
LOGIN_URL = "https://www2.kolhalashon.com/#/login/%2FregularSite%2Fnew"
CONFIG_FILE = Path("config.ini")

class Scraper:
    def __init__(self, status_callback=None):
        self.driver = None
        self.status_callback = status_callback
        self.topics_data = None
        self.temp_download_path = str(Path.home() / 'Downloads' / 'kol_halashon_temp')
        os.makedirs(self.temp_download_path, exist_ok=True)
        self.final_download_path = str(Path.home() / 'Downloads')

    def set_final_download_path(self, path):
        self.final_download_path = path
        self._update_status(f"ההורדות הבאות יישמרו ב: {self.final_download_path}")
        logger.info(f"Final download path set to: {self.final_download_path}")

    def _update_status(self, message):
        if self.status_callback:
            self.status_callback(message)

    def _create_webdriver(self):
        self._update_status("בודק הגדרות דרייבר...")
        logger.info("Attempting to create webdriver.")
        
        config = configparser.ConfigParser()
        driver_path = None

        if CONFIG_FILE.exists():
            config.read(CONFIG_FILE)
            if 'Paths' in config and 'driver_path' in config['Paths']:
                saved_path = config['Paths']['driver_path']
                if os.path.exists(saved_path):
                    driver_path = saved_path
                    logger.info(f"Using saved driver path from config.ini: {driver_path}")
                    self._update_status("משתמש בנתיב דרייבר שמור.")
                else:
                    logger.warning(f"Saved driver path not found: {saved_path}. Will try webdriver-manager.")

        if not driver_path:
            try:
                self._update_status("מנסה לאתר דרייבר אוטומטית...")
                logger.info("No valid saved path. Trying webdriver-manager.")
                service = ChromeService(ChromeDriverManager().install())
            except Exception as e:
                logger.error(f"Webdriver-manager failed: {e}")
                self._update_status("איתור אוטומטי נכשל. יש לבחור קובץ דרייבר ידנית.")
                
                root = tk.Tk()
                root.withdraw()
                driver_path = filedialog.askopenfilename(
                    title="אנא בחר את קובץ chromedriver.exe",
                    filetypes=[("Executable files", "*.exe")]
                )
                root.destroy()

                if driver_path:
                    logger.info(f"User selected manual driver path: {driver_path}")
                    config['Paths'] = {'driver_path': driver_path}
                    with open(CONFIG_FILE, 'w') as configfile:
                        config.write(configfile)
                    logger.info(f"Saved new driver path to {CONFIG_FILE}")
                    service = ChromeService(executable_path=driver_path)
                else:
                    logger.critical("User did not select a driver. Aborting.")
                    self._update_status("לא נבחר דרייבר. לא ניתן להמשיך.")
                    raise RuntimeError("לא נבחר דרייבר.")
        else:
            service = ChromeService(executable_path=driver_path)

        self._update_status("מפעיל את הדפדפן...")
        chrome_options = ChromeOptions()
        if RUN_HEADLESS:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1400,900")
        chrome_options.add_argument("--disable-features=RendererCodeIntegrity")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        prefs = {"download.default_directory": self.temp_download_path}
        chrome_options.add_experimental_option("prefs", prefs)
        
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver

    def _js_click(self, element):
        self.driver.execute_script("arguments[0].click();", element)

    def perform_login(self):
        if not self.driver:
            self.driver = self._create_webdriver()
        self._update_status("מתחיל תהליך התחברות...")
        logger.info("Navigating to login page.")
        self.driver.get(LOGIN_URL)
        try:
            WebDriverWait(self.driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[formcontrolname='code']"))).send_keys(CODE_VALUE)
            password_input = self.driver.find_element(By.CSS_SELECTOR, "input[formcontrolname='password']")
            password_input.send_keys(PASSWORD_VALUE)
            password_input.send_keys(webdriver.common.keys.Keys.ENTER)
            WebDriverWait(self.driver, 25).until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".banner-search input, .banner-title input")))
            self._update_status("✅ התחברות בוצעה בהצלחה.")
            logger.info("Login successful.")
            return True
        except TimeoutException:
            self._update_status("❌ שגיאה: התחברות נכשלה.")
            logger.error("Login failed (timeout).")
            return False

    def load_topics_from_file(self):
        if self.topics_data: return self.topics_data
        if not TOPICS_FILE.exists(): return None
        with open(TOPICS_FILE, 'r', encoding='utf-8') as f:
            self.topics_data = json.load(f)
        return self.topics_data

    def _get_current_shiurim_and_filters(self):
        self._update_status("טוען שיעורים ומסננים...")
        logger.info("Extracting shiurim and filters from page.")
        try:
            shiurim_list = self.driver.execute_script("""
            let shiurs = [];
            document.querySelectorAll('app-shiurim-display .shiur-container').forEach((el, i) => {
                let title = el.querySelector('.shiurim-title')?.textContent.trim() || '';
                let rav = el.querySelector('.shiurim-rav-name')?.textContent.trim() || '';
                let date = el.querySelector('.shiurim-start-time')?.textContent.trim() || '';
                shiurs.push({id: i, title: title, rav: rav, date: date});
            });
            return shiurs;
            """)
        except Exception as e:
            shiurim_list = []
            self._update_status("אזהרה: שגיאה בקריאת פרטי השיעורים.")
            logger.warning(f"Could not extract shiurim via JS: {e}")
        filters_data = []
        try:
            # --- FIX: בדיקה אם רכיב המסננים קיים לפני שמנסים לגשת אליו ---
            if self.driver.find_elements(By.CSS_SELECTOR, "app-filter-container"):
                filter_groups = self.driver.find_elements(By.CSS_SELECTOR, "app-filter-container")
                for group in filter_groups:
                    header = group.find_element(By.CSS_SELECTOR, ".filter-header")
                    category_title = header.text.strip()
                    if not category_title: continue
                    inner_container = group.find_element(By.CSS_SELECTOR, ".filter-container")
                    if "opened" not in inner_container.get_attribute("class"): self._js_click(header); time.sleep(0.5)
                    while True:
                        try:
                            show_more = group.find_element(By.XPATH, ".//div[contains(@class, 'display-more') and contains(normalize-space(), 'הצג עוד')]")
                            self._js_click(show_more); time.sleep(0.5)
                        except NoSuchElementException: break
                    WebDriverWait(self.driver, 5).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "mat-checkbox.filter-option")))
                    time.sleep(0.5)
                    options = group.find_elements(By.CSS_SELECTOR, "mat-checkbox.filter-option")
                    category_filters = []
                    for option in options:
                        label_el = option.find_element(By.CSS_SELECTOR, ".mat-checkbox-label")
                        full_label = self.driver.execute_script("return arguments[0].textContent;", label_el).strip().replace('\n', ' ').replace('  ', ' ')
                        if full_label:
                            category_filters.append(full_label)
                    if category_filters:
                        filters_data.append({'category_name': category_title, 'filters': category_filters})
        except Exception as e:
            self._update_status(f"אזהרה: לא ניתן היה לטעון מסננים.")
            logger.warning(f"Could not extract filters: {e}")
        self._update_status(f"נמצאו {len(shiurim_list)} שיעורים ו-{len(filters_data)} קטגוריות סינון.")
        logger.info(f"Found {len(shiurim_list)} shiurim and {len(filters_data)} filter categories.")
        return {'type': 'shiurim_and_filters', 'data': {'shiurim': shiurim_list, 'filters': filters_data}}

    def _handle_results_page(self):
        try:
            WebDriverWait(self.driver, 20).until(EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "app-shiurim-display .shiur-container")),
                EC.presence_of_element_located((By.CSS_SELECTOR, ".rav-container"))
            ))
            time.sleep(2)
            rav_results = self.driver.find_elements(By.CSS_SELECTOR, ".rav-container")
            if rav_results:
                rav_list = self.driver.execute_script("""
                let ravs = [];
                document.querySelectorAll('.rav-container').forEach((el, i) => {
                    let name = el.querySelector('.rav-name')?.textContent.trim() || '';
                    let count = el.querySelector('.rav-shiurim-sum')?.textContent.trim() || '';
                    ravs.push({id: i, name: name, count: count});
                });
                return ravs;
                """)
                return {'type': 'rav_selection', 'data': rav_list}
            return self._get_current_shiurim_and_filters()
        except TimeoutException:
            return {'type': 'error', 'message': 'לא נמצאו תוצאות.'}

    def refresh_current_page(self):
        self._update_status("מרענן נתונים מהעמוד הנוכחי...")
        logger.info("Refreshing data from current page.")
        return self._handle_results_page()

    def perform_search(self, query: str):
        self._update_status(f"מבצע חיפוש: '{query}'...")
        logger.info(f"Performing search for: '{query}'")
        search_type = "ravSearch" if query.strip().startswith("הרב") else "searchResults"
        encoded_query = urllib.parse.quote(query)
        self.driver.execute_script(f"window.location.hash = '#/regularSite/{search_type}/{encoded_query}';")
        return self._handle_results_page()

    def navigate_to_topic_by_href(self, href: str):
        self._update_status("מנווט לקטגוריה...")
        logger.info(f"Navigating to topic: {href}")
        self.driver.get(href)
        return self._handle_results_page()

    def select_rav_from_results(self, rav_id: int):
        self._update_status("בוחר רב מהרשימה...")
        logger.info(f"Selecting rav with ID: {rav_id}")
        fresh_rav_results = self.driver.find_elements(By.CSS_SELECTOR, ".rav-container")
        if rav_id >= len(fresh_rav_results):
            self._update_status("❌ שגיאה: הרב הנבחר לא נמצא. נסה לרענן.")
            logger.error(f"IndexError: rav_id {rav_id} is out of bounds for results list of size {len(fresh_rav_results)}.")
            return {'type': 'error', 'message': 'הרב לא נמצא'}
        self._js_click(fresh_rav_results[rav_id].find_element(By.CSS_SELECTOR, "a.rav-name"))
        WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "app-shiurim-display .shiur-container")))
        return self._get_current_shiurim_and_filters()

    def apply_filter_by_name(self, filter_name: str):
        self._update_status(f"מפעיל מסנן: {filter_name}...")
        logger.info(f"Applying filter: {filter_name}")
        try:
            first_shiur_element = None
            try:
                first_shiur_element = self.driver.find_element(By.CSS_SELECTOR, "app-shiurim-display .shiur-container")
            except NoSuchElementException:
                pass 
            
            click_script = """
            const filterName = arguments[0];
            const checkboxes = document.querySelectorAll('mat-checkbox.filter-option');
            for (const cb of checkboxes) {
                const label = cb.querySelector('.mat-checkbox-label');
                if (label && label.textContent.trim().includes(filterName)) {
                    cb.querySelector('input').click();
                    return true;
                }
            }
            return false;
            """
            clicked = self.driver.execute_script(click_script, filter_name)
            if not clicked:
                raise Exception("לא נמצא מסנן עם השם המבוקש.")

            if first_shiur_element:
                WebDriverWait(self.driver, 20).until(EC.staleness_of(first_shiur_element))
            
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "app-shiurim-display"))
            )
            time.sleep(1)

            return self._get_current_shiurim_and_filters()
        except Exception as e:
            logger.error(f"Error in apply_filter_by_name for '{filter_name}': {e}")
            self._update_status(f"❌ שגיאה בהפעלת המסנן: {filter_name}")
            return {'type': 'error', 'message': f'שגיאה בהפעלת המסנן'}
            
    def download_shiur_by_id(self, shiur_id: int):
        self._update_status(f"מתחיל הורדה לתיקייה זמנית...")
        logger.info(f"Initiating download for shiur ID: {shiur_id}")
        
        path_to_watch = self.temp_download_path
        files_before = set(os.listdir(path_to_watch))

        shiur_elements = self.driver.find_elements(By.CSS_SELECTOR, "app-shiurim-display .shiur-container")
        self._js_click(shiur_elements[shiur_id].find_element(By.XPATH, ".//button[.//svg-icon[contains(@src, 'download-i.svg')]]"))
        try:
            audio_option = WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.XPATH, "//div[contains(@class, 'download-option')]")))
            self._js_click(audio_option)
        except TimeoutException: pass

        self._update_status("ממתין לסיום ההורדה...")
        logger.info("Waiting for download to complete...")
        
        wait_time = 300
        start_time = time.time()
        new_file_path = None
        
        while time.time() - start_time < wait_time:
            files_after = set(os.listdir(path_to_watch))
            new_files = files_after - files_before
            if new_files:
                for f in new_files:
                    if not f.endswith('.crdownload') and not f.endswith('.tmp'):
                        new_file_path = os.path.join(path_to_watch, f)
                        break
            if new_file_path:
                break
            time.sleep(1)

        if not new_file_path:
            self._update_status("❌ שגיאה: ההורדה לא הסתיימה בזמן.")
            logger.error("Download timed out.")
            return

        self._update_status("מעביר את הקובץ ליעד הסופי...")
        logger.info(f"Download finished: {new_file_path}. Moving to {self.final_download_path}")
        
        filename = os.path.basename(new_file_path)
        destination_path = os.path.join(self.final_download_path, filename)
        
        counter = 1
        while os.path.exists(destination_path):
            name, ext = os.path.splitext(filename)
            destination_path = os.path.join(self.final_download_path, f"{name} ({counter}){ext}")
            counter += 1
            
        shutil.move(new_file_path, destination_path)
        
        self._update_status(f"✅ הורדה הושלמה ונשמרה ב: {self.final_download_path}")
        logger.info(f"File moved successfully to {destination_path}")
        
    def navigate_to_next_page(self):
        try:
            self._update_status("עובר לעמוד הבא...")
            logger.info("Navigating to next page.")
            next_button = self.driver.find_element(By.CSS_SELECTOR, "app-pagination-options .next:not(.disabled)")
            self._js_click(next_button)
            return self._handle_results_page()
        except NoSuchElementException:
            self._update_status("אין עמוד הבא.")
            logger.info("No next page button found.")
            return None

    def close_driver(self):
        if self.driver:
            logger.info("Closing webdriver.")
            self.driver.quit()