# scraper_logic.py (FIXED - REMOVED CIRCULAR IMPORT)
import time
from datetime import datetime
import json
import urllib.parse
from pathlib import Path
import logging
import configparser
import os
from tkinter import filedialog
import tkinter as tk
import shutil
import threading
import queue

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logger = logging.getLogger(__name__)

CODE_VALUE = "409573"
PASSWORD_VALUE = "220106"
RUN_HEADLESS = False
TOPICS_FILE = Path("topics.json")
LOGIN_URL = "https://www2.kolhalashon.com/#/login/%2FregularSite%2Fnew"
CONFIG_FILE = Path("config.ini")

def _create_webdriver_standalone(status_callback):
    status_callback("בודק הגדרות דרייבר...")
    config = configparser.ConfigParser()
    service = None
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
        if 'Paths' in config and 'driver_path' in config['Paths']:
            saved_path = config['Paths']['driver_path']
            if os.path.exists(saved_path):
                status_callback("משתמש בנתיב דרייבר שמור.")
                service = ChromeService(executable_path=saved_path)
    if not service:
        try:
            status_callback("מנסה לאתר דרייבר אוטומטית...")
            service = ChromeService(ChromeDriverManager().install())
        except Exception as e:
            status_callback("איתור אוטומטי נכשל. יש לבחור קובץ דרייבר ידנית.")
            root = tk.Tk(); root.withdraw()
            file_types = [("All files", "*.*")] if platform.system() == "Darwin" else [("Executable files", "*.exe")]
            manual_path = filedialog.askopenfilename(title="אנא בחר את קובץ chromedriver", filetypes=file_types)
            root.destroy()
            if manual_path:
                config['Paths'] = {'driver_path': manual_path}
                with open(CONFIG_FILE, 'w') as configfile: config.write(configfile)
                service = ChromeService(executable_path=manual_path)
            else:
                status_callback("לא נבחר דרייבר. לא ניתן להמשיך.")
                return None
    status_callback("מפעיל את הדפדפן...")
    chrome_options = ChromeOptions()
    if RUN_HEADLESS: chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    temp_download_path = str(Path.home() / 'Downloads' / 'kol_halashon_temp')
    os.makedirs(temp_download_path, exist_ok=True)
    
    prefs = {
        "download.default_directory": temp_download_path,
        "profile.default_content_setting_values.automatic_downloads": 1
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    return webdriver.Chrome(service=service, options=chrome_options)

def initial_login(status_callback):
    driver = _create_webdriver_standalone(status_callback)
    if not driver: return None
    status_callback("מתחיל תהליך התחברות...")
    driver.get(LOGIN_URL)
    try:
        WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[formcontrolname='code']"))).send_keys(CODE_VALUE)
        password_input = driver.find_element(By.CSS_SELECTOR, "input[formcontrolname='password']")
        password_input.send_keys(PASSWORD_VALUE)
        password_input.send_keys(webdriver.common.keys.Keys.ENTER)
        WebDriverWait(driver, 25).until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".banner-search input, .banner-title input")))
        status_callback("✅ התחברות בוצעה בהצלחה.")
        return driver
    except Exception as e:
        status_callback(f"❌ שגיאה: התחברות נכשלה. {e}")
        driver.quit()
        return None

class Scraper:
    def __init__(self, driver, status_callback=None, download_progress_callback=None):
        self.driver = driver
        self.status_callback = status_callback
        self.download_progress_callback = download_progress_callback
        self.topics_data = None
        self.temp_download_path = str(Path.home() / 'Downloads' / 'kol_halashon_temp')
        self.final_download_path = str(Path.home())
        self.driver_lock = threading.Lock()

        self.download_queue = queue.Queue()
        # --- NEW: The "message board" to link file IDs to download IDs ---
        self.active_downloads = {}
        self.monitor_lock = threading.Lock()

        self.download_worker_thread = threading.Thread(target=self._download_worker, daemon=True)
        self.file_monitor_thread = threading.Thread(target=self._file_monitor, daemon=True)
        self.download_worker_thread.start()
        self.file_monitor_thread.start()

    def set_final_download_path(self, path):
        target = os.path.join(path, "קול הלשון")
        os.makedirs(target, exist_ok=True)
        self.final_download_path = target
        self._update_status(f"ההורדות יישמרו ב: {self.final_download_path}")

    def _update_status(self, message):
        if self.status_callback: self.status_callback(message)
            
    def _update_download_progress(self, did, prog, stat):
        if self.download_progress_callback: self.download_progress_callback(did, prog, stat)

    def _js_click(self, element):
        self.driver.execute_script("arguments[0].click();", element)

    def _wait_for_file_ready(self, path, timeout=15):
        start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(path):
                try:
                    with open(path, 'rb') as f: f.read(1)
                    return True
                except (IOError, PermissionError): time.sleep(0.5)
            else: time.sleep(0.5)
        return False

    def _try_move_file(self, src_path, dest_dir, max_attempts=5, wait_timeout=20):
        if not self._wait_for_file_ready(src_path, timeout=wait_timeout):
            logger.warning(f"File never became ready: {src_path}")
            return None
        filename = os.path.basename(src_path)
        for attempt in range(max_attempts):
            try:
                name, ext = os.path.splitext(filename)
                candidate = os.path.join(dest_dir, filename)
                counter = 1
                while os.path.exists(candidate):
                    candidate = os.path.join(dest_dir, f"{name} ({counter}){ext}")
                    counter += 1
                shutil.move(src_path, candidate)
                logger.info(f"Successfully moved {src_path} to {candidate}")
                return candidate
            except Exception as e:
                logger.warning(f"Move attempt {attempt+1} failed for {src_path}: {e}")
                time.sleep(1)
        return None

    def load_topics_from_file(self):
        if self.topics_data: return self.topics_data
        if not TOPICS_FILE.exists(): return None
        with open(TOPICS_FILE, 'r', encoding='utf-8') as f:
            self.topics_data = json.load(f)
        return self.topics_data

    def get_initial_page_data(self):
        self._update_status("טוען נתונים ראשוניים...")
        try:
            script = """
            const shiurim = Array.from(document.querySelectorAll('app-shiurim-display .shiur-container')).map((el, i) => ({
                id: i,
                title: el.querySelector('.shiurim-title')?.textContent.trim() || '',
                rav: el.querySelector('.shiurim-rav-name')?.textContent.trim() || '',
                date: el.querySelector('.shiurim-start-time')?.textContent.trim() || ''
            }));
            const filter_categories = Array.from(document.querySelectorAll('app-filter-container .filter-header'))
                .map(header => header.textContent.trim()).filter(Boolean);
            return { shiurim, filter_categories };
            """
            return self.driver.execute_script(script)
        except Exception as e:
            logger.error(f"Failed to get initial page data: {e}")
            return {'shiurim': [], 'filter_categories': []}

    def expand_and_get_all_filters(self):
        self._update_status("מרחיב מסננים ברקע...")
        try:
            self.driver.execute_script("""
                document.querySelectorAll('app-filter-container .filter-header').forEach(h => {
                    const c = h.closest('app-filter-container').querySelector('.filter-container');
                    if (c && !c.classList.contains('opened')) h.click();
                });
            """)
            time.sleep(0.3)
            for i in range(20):
                self._update_status(f"מרחיב מסננים... (שלב {i+1})")
                clicked_something = self.driver.execute_script("""
                    let clicked = false;
                    const showMoreButtons = Array.from(document.querySelectorAll(".display-more"))
                                                .filter(btn => btn.textContent.includes('הצג עוד') && btn.offsetParent);
                    if (showMoreButtons.length > 0) { showMoreButtons.forEach(btn => btn.click()); clicked = true; }
                    const closedArrowButtons = Array.from(document.querySelectorAll(".nested-filter-container:not(.expanded-nested-filter-container) .icon-nav-arrow, .scroll-container > .nested-filter-container:not(.expanded-nested-filter-container) .icon-nav-arrow"))
                                                   .filter(arrow => arrow.offsetParent);
                    if (closedArrowButtons.length > 0) { closedArrowButtons.forEach(arrow => arrow.click()); clicked = true; }
                    return clicked;
                """)
                if not clicked_something: break
                time.sleep(0.8)
            self._update_status("אוסף את רשימת המסננים...")
            filters_data = self.driver.execute_script("""
            function getElementText(el) {
                const title = el.querySelector('.filter-title')?.textContent.trim() || '';
                const count = el.querySelector('.shiurim-count')?.textContent.trim() || '';
                if (!title && el.classList.contains('mat-checkbox')) { return el.textContent.trim(); }
                return `${title} ${count}`.trim();
            }
            function parseContainer(container, level) {
                let results = [];
                const children = container.querySelectorAll(':scope > .nested-flex-display, :scope > mat-checkbox.filter-option, :scope > .nested-filter-container, :scope > div > mat-checkbox.filter-option');
                children.forEach(child => {
                    if (child.matches('mat-checkbox.filter-option, .nested-flex-display')) {
                        const text = getElementText(child);
                        if (text) results.push({ text: text, level: level });
                    } else if (child.matches('.nested-filter-container')) {
                        results = results.concat(parseContainer(child, level + 1));
                    }
                });
                return results;
            }
            const topLevelContainers = document.querySelectorAll('app-filter-container');
            let allFilters = [];
            topLevelContainers.forEach(topContainer => {
                const categoryName = topContainer.querySelector('.filter-header')?.textContent.trim();
                if (!categoryName) return;
                allFilters.push({ text: categoryName, level: -1 });
                const content = topContainer.querySelector('.filter-content > .scroll-container, .filter-content');
                if (content) allFilters = allFilters.concat(parseContainer(content, 0));
            });
            return allFilters;
            """)
            self._update_status("טעינת המסננים הושלמה.")
            return filters_data
        except Exception as e:
            self._update_status("שגיאה בטעינת המסננים.")
            logger.error(f"Failed to expand and get filters: {e}", exc_info=True)
            return []

    def _handle_results_page(self):
        self._update_status("ממתין לטעינת העמוד...")
        try:
            WebDriverWait(self.driver, 15).until(EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "app-shiurim-display .shiur-container")),
                EC.presence_of_element_located((By.CSS_SELECTOR, ".rav-container"))
            ))
            time.sleep(1)
            if self.driver.find_elements(By.CSS_SELECTOR, ".rav-container"):
                return {'type': 'rav_selection', 'data': self.driver.execute_script("""
                    return Array.from(document.querySelectorAll('.rav-container')).map((el, i) => ({
                        id: i, name: el.querySelector('.rav-name')?.textContent.trim(),
                        count: el.querySelector('.rav-shiurim-sum')?.textContent.trim()
                    }));""")}
            if self.driver.find_elements(By.CSS_SELECTOR, "app-shiurim-display .shiur-container"):
                try:
                    WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "app-filter-container")))
                except TimeoutException:
                    logger.warning("Filter container did not appear in time.")
                return {'type': 'initial_data', 'data': self.get_initial_page_data()}
            return {'type': 'error', 'message': 'לא נמצא תוכן מתאים.'}
        except TimeoutException:
            return {'type': 'error', 'message': 'העמוד לא נטען בזמן.'}

    def refresh_browser_page(self):
        self._update_status("מרענן את הדף...")
        self.driver.refresh()
        return self._handle_results_page()

    def refresh_current_page_content(self):
        self._update_status("טוען נתונים מחדש...")
        return self._handle_results_page()

    def perform_search(self, query: str):
        self._update_status(f"חיפוש: '{query}'...")
        search_type = "ravSearch" if query.strip().startswith("הרב") else "searchResults"
        self.driver.get(f"https://www2.kolhalashon.com/#/regularSite/{search_type}/{urllib.parse.quote(query)}")
        return self._handle_results_page()

    def navigate_to_topic_by_href(self, href: str):
        self._update_status("מנווט לקטגוריה...")
        self.driver.get(href)
        return self._handle_results_page()

    def select_rav_from_results(self, rav_id: int):
        self._update_status("בוחר רב...")
        with self.driver_lock:
            rav_links = self.driver.find_elements(By.CSS_SELECTOR, ".rav-container a.rav-name")
            if rav_id < len(rav_links): self._js_click(rav_links[rav_id])
            else: return {'type': 'error', 'message': 'הרב לא נמצא.'}
        return self._handle_results_page()

    def apply_filter_by_name(self, filter_name: str):
        self._update_status(f"מפעיל מסנן: {filter_name}...")
        try:
            with self.driver_lock:
                first_shiur = self.driver.find_element(By.CSS_SELECTOR, "app-shiurim-display .shiur-container")
                self.driver.execute_script("""
                    const filterText = arguments[0];
                    for (const cb of document.querySelectorAll('mat-checkbox')) {
                        const labelContent = Array.from(cb.querySelectorAll('.filter-title, .shiurim-count'))
                                                  .map(el => el.textContent.trim()).join(' ').trim();
                        if (labelContent === filterText || cb.textContent.trim() === filterText) {
                            cb.querySelector('input').click(); return;
                        }
                    }
                """, filter_name)
                WebDriverWait(self.driver, 20).until(EC.staleness_of(first_shiur))
            return self._handle_results_page()
        except Exception as e:
            return {'type': 'error', 'message': f'שגיאה בהפעלת המסנן: {e}'}

    def queue_download(self, shiur_id, title, did):
        self.download_queue.put({'shiur_id': shiur_id, 'title': title, 'did': did})
        self._update_download_progress(did, 0, "starting")

    def _download_worker(self):
        while True:
            task = self.download_queue.get()
            shiur_id, title, did = task['shiur_id'], task['title'], task['did']
            
            self._update_status(f"מתחיל הורדה: {title}")
            try:
                with self.driver_lock:
                    shiur_elements = self.driver.find_elements(By.CSS_SELECTOR, "app-shiurim-display .shiur-container")
                    if shiur_id >= len(shiur_elements):
                        raise IndexError("Shiur ID out of bounds")
                    
                    try:
                        phone_button = shiur_elements[shiur_id].find_element(By.XPATH, ".//button[contains(@class, 'click-phone-button')]")
                        file_id = phone_button.text.strip()
                        if file_id:
                            with self.monitor_lock:
                                self.active_downloads[file_id] = did
                                logger.info(f"Registered download: file_id {file_id} maps to did {did}")
                    except NoSuchElementException:
                        logger.warning(f"Could not find file_id for {title}. UI update will not work for this download.")

                    download_button = shiur_elements[shiur_id].find_element(By.XPATH, ".//button[.//svg-icon[contains(@src, 'download-i.svg')]]")
                    self._js_click(download_button)
                    
                    try:
                        audio_option = WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.XPATH, "//div[contains(@class, 'download-option')]")))
                        self._js_click(audio_option)
                    except TimeoutException:
                        pass
                    
                    time.sleep(1.5) 
            except Exception as e:
                logger.error(f"Failed to initiate download for {title}: {e}")
                self._update_download_progress(did, 0, "failed")
            
            self.download_queue.task_done()
            time.sleep(1)

    def _file_monitor(self):
        processed_files = set()
        while True:
            try:
                all_files = set(os.listdir(self.temp_download_path))
                completed_files = [f for f in all_files if not f.endswith(('.crdownload', '.tmp')) and f not in processed_files]

                for fname in completed_files:
                    full_path = os.path.join(self.temp_download_path, fname)
                    processed_files.add(fname)
                    
                    did_to_update = None
                    file_id_found = None
                    with self.monitor_lock:
                        for file_id, did in self.active_downloads.items():
                            if file_id in fname:
                                did_to_update = did
                                file_id_found = file_id
                                break
                    
                    if self._try_move_file(full_path, self.final_download_path):
                        logger.info(f"Moved downloaded file: {fname}")
                        if did_to_update:
                            self._update_download_progress(did_to_update, 1, "completed")
                            with self.monitor_lock:
                                del self.active_downloads[file_id_found]
                    else:
                        logger.error(f"Failed to move {fname} from temp folder.")
                        if did_to_update:
                            self._update_download_progress(did_to_update, 0, "failed")
                            with self.monitor_lock:
                                del self.active_downloads[file_id_found]
                
                if len(processed_files) > 100:
                    processed_files.clear()

            except Exception as e:
                logger.error(f"Error in file monitor: {e}")
            
            time.sleep(2)

    def navigate_to_next_page(self):
        try:
            self._update_status("עובר לעמוד הבא...")
            with self.driver_lock:
                next_button = self.driver.find_element(By.CSS_SELECTOR, "app-pagination-options .next:not(.disabled)")
                self._js_click(next_button)
            return self._handle_results_page()
        except NoSuchElementException:
            self._update_status("אין עמוד הבא.")
            return None

    def close_driver(self):
        if self.driver: self.driver.quit()
