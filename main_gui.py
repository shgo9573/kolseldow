# main_gui.py
import customtkinter as ctk
import threading
from scraper_logic import Scraper
from tkinter import Menu
import platform
import logging
from pathlib import Path

if platform.system() == "Windows":
    from win32api import GetLogicalDriveStrings, GetVolumeInformation
    
def rtl_fix(text):
    text_str = str(text)
    words = text_str.split()
    reversed_words = words[::-1]
    return " ".join(reversed_words)

def setup_logging():
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler = logging.FileHandler('app_log.log', encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_formatter)
    stream_handler.setLevel(logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

logger = logging.getLogger(__name__)

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        ctk.set_appearance_mode("Light")

        self.title(rtl_fix("ממשק כל השיעורים"))
        self.geometry("1200x750")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        self.scraper = Scraper(status_callback=self.update_status)
        self.is_logged_in = False
        self.topics_data = None
        self.active_filters = set()
        
        self.filter_checkboxes = []
        self.original_checkbox_text = {}

        self.create_widgets()
        self.start_login()

    def create_widgets(self):
        # --- סרגל עליון ---
        self.top_frame = ctk.CTkFrame(self, height=50, corner_radius=0)
        self.top_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.top_frame.grid_columnconfigure(4, weight=1)
        self.top_frame.grid_rowconfigure(1, weight=1)

        instruction_label = ctk.CTkLabel(self.top_frame, text=rtl_fix("לחיפוש רבנים יש להוסיף 'הרב' בתחילת החיפוש"), font=ctk.CTkFont(size=11), text_color="gray50")
        instruction_label.grid(row=0, column=4, sticky="se", padx=(10,5), pady=(2,0))

        self.search_entry = ctk.CTkEntry(self.top_frame, placeholder_text=rtl_fix("הזן שם רב או שיעור לחיפוש..."), justify="right")
        self.search_entry.grid(row=1, column=4, padx=(10, 5), pady=(0, 10), sticky="ew")
        self.search_entry.bind("<Return>", self.start_search)
        
        self.search_button = ctk.CTkButton(self.top_frame, text=rtl_fix("חיפוש"), width=100, command=self.start_search)
        self.search_button.grid(row=1, column=3, padx=(5, 5), pady=(0, 10))
        
        self.reload_button = ctk.CTkButton(self.top_frame, text=rtl_fix("רענן דף"), width=100, command=self.start_browser_refresh)
        self.reload_button.grid(row=1, column=2, padx=(5, 5), pady=(0, 10))
        
        self.re_extract_button = ctk.CTkButton(self.top_frame, text=rtl_fix("טען מחדש"), width=100, command=self.start_content_refresh)
        self.re_extract_button.grid(row=1, column=1, padx=(5, 5), pady=(0, 10))
        
        self.categories_button = ctk.CTkButton(self.top_frame, text=rtl_fix("קטגוריות"), width=120)
        self.categories_button.grid(row=1, column=0, padx=(10, 5), pady=(0, 10))
        self.categories_menu = Menu(self.categories_button, tearoff=0)
        self.categories_button.configure(command=self.show_categories_menu)

        # --- פאנל שמאלי (מסננים) ---
        self.filters_panel = ctk.CTkFrame(self, width=300)
        self.filters_panel.grid(row=1, column=0, sticky="ns", padx=10, pady=10)
        self.filters_panel.grid_rowconfigure(2, weight=1)
        
        ctk.CTkLabel(self.filters_panel, text=rtl_fix("מסננים זמינים"), font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=(10,5), sticky="ew")
        self.filter_search_entry = ctk.CTkEntry(self.filters_panel, placeholder_text=rtl_fix("מצא מסנן..."), justify="right")
        self.filter_search_entry.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        self.filter_search_entry.bind("<KeyRelease>", self.filter_checkbox_list)
        self.filters_scroll_frame = ctk.CTkScrollableFrame(self.filters_panel, label_text="")
        self.filters_scroll_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)

        # --- פאנל ימני (תוצאות) ---
        self.results_outer_frame = ctk.CTkFrame(self)
        self.results_outer_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 10), pady=5)
        self.results_outer_frame.grid_rowconfigure(1, weight=1)
        self.results_outer_frame.grid_columnconfigure(0, weight=1)
        
        self.active_filters_frame = ctk.CTkFrame(self.results_outer_frame, fg_color="transparent")
        self.active_filters_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=0)
        self.results_frame = ctk.CTkScrollableFrame(self.results_outer_frame, label_text=rtl_fix("תוצאות"))
        self.results_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=0)
        
        # --- סרגל תחתון ---
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.bottom_frame.grid_columnconfigure(1, weight=1)

        self.pagination_frame = ctk.CTkFrame(self.bottom_frame)
        self.pagination_frame.grid(row=0, column=1, sticky="ew", padx=10, pady=(0, 10))
        self.pagination_frame.grid_columnconfigure(1, weight=1)
        
        self.drive_selector_frame = ctk.CTkFrame(self.pagination_frame, fg_color="transparent")
        self.drive_selector_frame.grid(row=0, column=0, padx=10, pady=5)
        ctk.CTkLabel(self.drive_selector_frame, text=rtl_fix("שמור בכונן:")).pack(side="right")
        self.setup_drive_selector()
        
        self.next_page_button = ctk.CTkButton(self.pagination_frame, text=rtl_fix("העמוד הבא ->"), command=self.go_to_next_page, state="disabled")
        self.next_page_button.grid(row=0, column=1, padx=10, pady=5)
        
        self.progress_bar = ctk.CTkProgressBar(self.bottom_frame, orientation="horizontal", mode="indeterminate")
        
        self.status_bar = ctk.CTkLabel(self, text=rtl_fix("ממתין..."), anchor="e", height=25)
        self.status_bar.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0,5))

    def get_drives(self):
        drives = []
        drive_map = {}
        if platform.system() == "Windows":
            try:
                drive_str = GetLogicalDriveStrings()
                raw_drives = [d for d in drive_str.split('\000') if d]
                for d in raw_drives:
                    try:
                        volume_name, _, _, _, _ = GetVolumeInformation(d)
                        display_name = f"{volume_name} ({d.strip()})" if volume_name else d.strip()
                        drives.append(display_name)
                        drive_map[display_name] = d
                    except Exception:
                        drives.append(d)
                        drive_map[d] = d
            except Exception as e:
                logger.error(f"Could not get drive list: {e}")
        return drives, drive_map

    def setup_drive_selector(self):
        drives, drive_map = self.get_drives()
        self.drive_map = drive_map
        self.drive_option_menu = ctk.CTkOptionMenu(self.drive_selector_frame, values=drives, command=self.on_drive_selected)
        if drives:
            self.drive_option_menu.set(drives[0])
            self.on_drive_selected(drives[0])
        self.drive_option_menu.pack(side="right", padx=5)

        refresh_drive_button = ctk.CTkButton(self.drive_selector_frame, text="🔄", width=28, height=28, command=self.refresh_drives)
        refresh_drive_button.pack(side="right", padx=(0, 5))

    def refresh_drives(self):
        new_drives, new_drive_map = self.get_drives()
        self.drive_map = new_drive_map
        self.drive_option_menu.configure(values=new_drives)
        if new_drives:
            self.drive_option_menu.set(new_drives[0])
            self.on_drive_selected(new_drives[0])
        self.update_status("רשימת הכוננים עודכנה.")

    def on_drive_selected(self, selected_display_name):
        path = self.drive_map.get(selected_display_name, str(Path.home() / 'Downloads'))
        self.scraper.set_final_download_path(path)

    def run_in_thread(self, target_func, callback=None, *args):
        def thread_target():
            self.progress_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5,0))
            self.progress_bar.start()
            self.set_ui_state("disabled")
            try:
                result = target_func(*args)
                if callback:
                    self.after(0, callback, result)
            except Exception as e:
                logger.error(f"Error in thread for {target_func.__name__}: {e}", exc_info=True)
                self.update_status(f"❌ שגיאה כללית. בדוק את קובץ הלוג.")
            finally:
                self.set_ui_state("normal")
                self.progress_bar.stop()
                self.progress_bar.grid_forget()
        threading.Thread(target=thread_target, daemon=True).start()

    def set_ui_state(self, state):
        self.search_button.configure(state=state)
        self.categories_button.configure(state=state)
        self.reload_button.configure(state="normal")
        self.re_extract_button.configure(state="normal")
        self.next_page_button.configure(state="disabled" if state == "disabled" else "normal")

    def update_status(self, message):
        self.status_bar.configure(text=rtl_fix(message))
        logger.info(f"Status Updated: {message}")

    def start_login(self):
        self.run_in_thread(self.scraper.perform_login, self.on_login_complete)

    def on_login_complete(self, success):
        if success:
            self.is_logged_in = True
            self.topics_data = self.scraper.load_topics_from_file()
            self.build_categories_menu()
            self.update_status("מוכן. נא לבצע חיפוש או לבחור קטגוריה.")
        else:
            self.update_status("כשלון בהתחברות. בדוק פרטים ונסה שוב.")

    def build_categories_menu(self):
        if not self.topics_data: return
        for main_cat_name, sub_cats in self.topics_data.items():
            sub_menu = Menu(self.categories_menu, tearoff=0)
            for sub_cat in sub_cats:
                sub_menu.add_command(label=rtl_fix(sub_cat['name']), command=lambda href=sub_cat['href']: self.run_in_thread(self.scraper.navigate_to_topic_by_href, self.handle_results, href))
            self.categories_menu.add_cascade(label=rtl_fix(main_cat_name), menu=sub_menu)

    def show_categories_menu(self):
        self.categories_menu.tk_popup(self.categories_button.winfo_rootx(), self.categories_button.winfo_rooty() + self.categories_button.winfo_height())

    def start_search(self, event=None):
        query = self.search_entry.get()
        if query and self.is_logged_in:
            self.run_in_thread(self.scraper.perform_search, self.handle_results, query)

    def start_browser_refresh(self):
        if not self.is_logged_in: return
        self.run_in_thread(self.scraper.refresh_browser_page, self.handle_results)

    def start_content_refresh(self):
        if not self.is_logged_in: return
        self.run_in_thread(self.scraper.refresh_current_page_content, self.handle_results)

    def clear_results_and_filters(self):
        for widget in self.results_frame.winfo_children(): widget.destroy()
        for widget in self.filters_scroll_frame.winfo_children(): widget.destroy()
        self.filter_checkboxes.clear()
        self.original_checkbox_text.clear()
        self.active_filters.clear()
        self.update_active_filters_display()
        self.next_page_button.configure(state="disabled")

    def handle_results(self, result):
        if not result: return
        self.clear_results_and_filters()
        result_type = result.get('type')
        
        if result_type == 'error':
            error_message = result.get('message', 'שגיאה לא ידועה')
            ctk.CTkLabel(self.results_frame, text=rtl_fix(f"שגיאה: {error_message}"), text_color="red").pack()
        elif result_type == 'rav_selection':
            data = result.get('data')
            for rav in data:
                ctk.CTkButton(self.results_frame, text=rtl_fix(f"{rav['name']} ({rav['count']})"),
                              command=lambda r_id=rav['id']: self.run_in_thread(self.scraper.select_rav_from_results, self.handle_results, r_id)).pack(fill="x", padx=10, pady=2)
        elif result_type == 'shiurim_and_filters':
            data = result.get('data')
            self.populate_results(data['shiurim'])
            self.populate_filters(data['filters'])
            if data['shiurim']: self.next_page_button.configure(state="normal")

    def populate_results(self, shiurim_list):
        if not shiurim_list:
            ctk.CTkLabel(self.results_frame, text=rtl_fix("לא נמצאו שיעורים.")).pack()
            return
        for shiur in shiurim_list:
            frame = ctk.CTkFrame(self.results_frame)
            frame.pack(fill="x", padx=5, pady=4)
            frame.grid_columnconfigure(0, weight=1)
            details_frame = ctk.CTkFrame(frame, fg_color="transparent")
            details_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
            ctk.CTkLabel(details_frame, text=rtl_fix(shiur['title']), justify="right", font=ctk.CTkFont(weight="bold")).pack(fill="x")
            ctk.CTkLabel(details_frame, text=rtl_fix(f"{shiur['rav']} | {shiur['date']}"), justify="right", font=ctk.CTkFont(size=10)).pack(fill="x")
            ctk.CTkButton(frame, text=rtl_fix("הורדה"), width=100,
                          command=lambda s_id=shiur['id']: threading.Thread(target=lambda: self.scraper.download_shiur_by_id(s_id), daemon=True).start()).grid(row=0, column=1, padx=10, pady=5)

    def populate_filters(self, filters_data):
        VISIBLE_FILTERS_COUNT = 5
        if not filters_data:
            ctk.CTkLabel(self.filters_scroll_frame, text=rtl_fix("אין מסננים זמינים")).pack()
            return
        
        for category in filters_data:
            ctk.CTkLabel(self.filters_scroll_frame, text=rtl_fix(category['category_name']), font=ctk.CTkFont(weight="bold")).pack(fill="x", pady=(10, 2))
            
            filters_in_category = category['filters']
            hidden_checkboxes = []
            
            for i, filter_name in enumerate(filters_in_category):
                var = ctk.StringVar(value="off")
                cb = ctk.CTkCheckBox(self.filters_scroll_frame, text=rtl_fix(filter_name), variable=var, onvalue="on", offvalue="off",
                                     command=lambda fn=filter_name, v=var: self.on_filter_toggled(fn, v.get()))
                
                if i < VISIBLE_FILTERS_COUNT:
                    cb.pack(fill="x", padx=10, pady=2)
                else:
                    hidden_checkboxes.append(cb)
                
                self.filter_checkboxes.append(cb)
                self.original_checkbox_text[cb] = filter_name

            if hidden_checkboxes:
                show_more_button = ctk.CTkButton(self.filters_scroll_frame, text=rtl_fix("הצג עוד"), fg_color="transparent", text_color=("gray10", "gray90"), hover=False)
                show_more_button.configure(command=lambda h_cbs=hidden_checkboxes, btn=show_more_button: self.toggle_show_more(h_cbs, btn))
                show_more_button.pack(fill="x", padx=10, pady=2)

    def toggle_show_more(self, hidden_widgets, button):
        if rtl_fix("הצג עוד") in button.cget("text"):
            for widget in hidden_widgets:
                widget.pack(fill="x", padx=10, pady=2)
            button.configure(text=rtl_fix("הצג פחות"))
        else:
            for widget in hidden_widgets:
                widget.pack_forget()
            button.configure(text=rtl_fix("הצג עוד"))

    def on_filter_toggled(self, filter_name, var_state):
        if var_state == "on": self.active_filters.add(filter_name)
        else: self.active_filters.discard(filter_name)
        self.update_active_filters_display()
        self.run_in_thread(self.scraper.apply_filter_by_name, self.handle_results, filter_name)

    def filter_checkbox_list(self, event=None):
        search_term = self.filter_search_entry.get()
        for cb in self.filter_checkboxes:
            original_text = self.original_checkbox_text[cb]
            if search_term in original_text:
                cb.pack(fill="x", padx=10, pady=2)
            else:
                cb.pack_forget()

    def update_active_filters_display(self):
        for widget in self.active_filters_frame.winfo_children(): widget.destroy()
        if self.active_filters:
            self.active_filters_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=0)
            ctk.CTkLabel(self.active_filters_frame, text=rtl_fix(":מסננים פעילים"), font=ctk.CTkFont(size=12)).pack(side="right", padx=(5,0))
            for filter_name in self.active_filters:
                ctk.CTkLabel(self.active_filters_frame, text=rtl_fix(filter_name), fg_color="gray30", corner_radius=6).pack(side="right", padx=3)
        else:
            self.active_filters_frame.grid_remove()

    def go_to_next_page(self):
        self.run_in_thread(self.scraper.navigate_to_next_page, self.handle_results)

    def on_closing(self):
        self.scraper.close_driver()
        self.destroy()

if __name__ == "__main__":
    setup_logging()
    logger.info("Application starting...")
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
    logger.info("Application closed.")
