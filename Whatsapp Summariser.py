# Import necessary libraries for the application
import tkinter as tk  # Python's standard GUI library.
from tkinter import filedialog, ttk, messagebox  # Specific Tkinter components for modern UIs.
import re  # Used for pattern matching in text (Regular Expressions).
from datetime import datetime, timedelta  # For handling dates and times.
import google.generativeai as genai  # The official Google Gemini AI library.
import threading  # To run tasks in the background without freezing the GUI.
import zipfile  # For reading and extracting from .zip files.
import io  # To handle files as in-memory text streams.
import base64  # To encode binary data (like images) into text.
import os  # For interacting with the operating system (e.g., file paths).
import configparser # To save and load application settings (like API key).
from tkinterdnd2 import DND_FILES, TkinterDnD # A library to add drag-and-drop support to Tkinter.
from PIL import Image, ImageTk # Pillow library for image processing and use in Tkinter.
import json # For handling JSON data from the Gemini API.
import tempfile # To create temporary directories for file storage.
import subprocess # To run external programs, like the default media viewer.
import sys # To check the operating system (e.g., Windows vs macOS).
import cv2 # OpenCV library for video processing.
import numpy as np # Required numerical library for OpenCV.

# --- NEW: Import libraries for data visualization ---
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# --- Core Functions ---

def get_mime_type(filename):
    """Gets the MIME type from a filename, required by the Gemini API."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in ['.jpg', '.jpeg']: return 'image/jpeg'
    elif ext == '.png': return 'image/png'
    elif ext == '.webp': return 'image/webp'
    return None

def parse_whatsapp_zip(zip_path):
    """Extracts messages and media file lists from a WhatsApp .zip export."""
    messages, image_list, video_list = [], [], []
    media_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.mp4')
    pattern = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4}, \d{2}:\d{2}) - (.*?): (.*?)(?:\s*\(file attached\))?$")

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            chat_filename = next((name for name in zf.namelist() if name.endswith('.txt')), None)
            if not chat_filename: raise FileNotFoundError("Chat .txt file not found in zip.")
            
            all_media_files = [name for name in zf.namelist() if name.lower().endswith(media_extensions)]
            image_list = [name for name in all_media_files if not name.lower().endswith('.mp4')]
            video_list = [name for name in all_media_files if name.lower().endswith('.mp4')]

            with zf.open(chat_filename) as chat_file:
                chat_content = io.TextIOWrapper(chat_file, encoding='utf-8')
                for line in chat_content:
                    match = pattern.match(line.strip())
                    if match:
                        datetime_str, author, message_text = match.groups()
                        image_filename = message_text if message_text in image_list else None
                        video_filename = message_text if message_text in video_list else None
                        try:
                            dt_obj = datetime.strptime(datetime_str, '%d/%m/%Y, %H:%M')
                            messages.append({'timestamp': dt_obj, 'author': author.strip(), 'message': message_text.strip(), 'image_filename': image_filename, 'video_filename': video_filename})
                        except ValueError: continue
    except Exception as e:
        messagebox.showerror("Parsing Error", f"Failed to parse zip file: {e}")
        return [], [], []
        
    return messages, image_list, video_list

def filter_messages_by_time(messages, time_range_str):
    """Filters messages to a specific time range."""
    if not messages: return []
    now = datetime.now()
    time_deltas = {"Last 24 hours": timedelta(days=1), "Last 7 days": timedelta(days=7), "Last 30 days": timedelta(days=30)}
    if time_range_str == "All time": return messages
    if time_range_str in time_deltas:
        start_time = now - time_deltas[time_range_str]
        return [msg for msg in messages if msg['timestamp'] >= start_time]
    return []

def format_chat_for_summary(messages):
    """Converts the list of message dictionaries into a single string for the AI."""
    formatted_lines = []
    for msg in messages:
        if msg['image_filename']: text = f"[Image Sent: {msg['image_filename']}]"
        elif msg['video_filename']: text = f"[Video Sent: {msg['video_filename']}]"
        else: text = msg['message']
        formatted_lines.append(f"[{msg['timestamp'].strftime('%Y-%m-%d %H:%M')}] {msg['author']}: {text}")
    return "\n".join(formatted_lines)

def extract_frame_from_video(zip_path, video_filename, temp_dir, as_thumbnail=False):
    """Extracts a single frame from a video using OpenCV."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            video_path = zf.extract(video_filename, path=temp_dir)
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened(): return None
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_no = int(total_frames * 0.1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            success, frame = cap.read()
            cap.release()
            
            if success:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(frame_rgb)
                
                if as_thumbnail:
                    pil_img.thumbnail((100, 100))
                    return pil_img

                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG")
                return base64.b64encode(buf.getvalue()).decode('utf-8')
            return None
    except Exception:
        return None

def get_summary_from_gemini(api_key, chat_text, detail_level, zip_path=None, image_filenames=None, video_filenames=None, temp_dir=None):
    """Sends chat data to the Gemini API for a structured JSON summary and sentiment analysis."""
    if not api_key: raise ValueError("API key is missing.")
    if not chat_text: return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        json_schema = {
            "type": "object",
            "properties": {
                "summary_parts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["text", "key_message", "media"]},
                            "content": {"type": "string"}, "author": {"type": "string"}, "filename": {"type": "string"}
                        }, "required": ["type"]
                    }
                },
                "bullet_points": {"type": "array", "items": {"type": "string"}},
                "sentiments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sentiment": {"type": "string"},
                            "count": {"type": "integer"}
                        }, "required": ["sentiment", "count"]
                    }
                }
            }
        }
        
        detail_map = {
            0: {"description": "an extremely brief summary, keeping the total text under 125 words", "quotes": "one single, impactful 'key_message'", "media": "one single 'media' part if media is available"},
            1: {"description": "a standard, medium-detail summary, keeping the total text under 125 words", "quotes": "2-3 'key_message' parts", "media": "2-3 'media' parts if media is available"},
            2: {"description": "an extremely verbose and comprehensive summary, keeping the total text under 500 words", "quotes": "at least 4-5 'key_message' parts", "media": "at least 4-5 'media' parts if media is available"}
        }
        detail_config = detail_map.get(detail_level, detail_map[1])
        detail_text, quotes_text, media_text = detail_config["description"], detail_config["quotes"], detail_config["media"]
        
        prompt_parts = [
            f"Analyse the following WhatsApp chat log. Provide a structured, {detail_text} summary in JSON format. ",
            "The summary should be broken into parts. Most parts should be of type 'text'. ",
            f"Crucially, you must identify {quotes_text}. Ensure these are from a variety of different authors if possible, not just one person. ",
            "For each part, provide the content and the author. For general summary text, the author can be 'narrator'. ",
            "Use the names of the people involved (e.g., 'Simon and Luke discussed...') instead of generic phrases like 'the chat says' or 'the users talked about'. ",
            f"If you discuss a specific image or video, create a 'media' part and set its 'filename' property. You should aim to include {media_text}. Then continue the summary in a new 'text' part.",
            "Provide a list of key 'bullet_points'. ",
            "Finally, analyze the overall sentiment. Provide a 'sentiments' array, categorizing the chat messages. Common sentiments might be 'Positive', 'Negative', 'Neutral', 'Humorous', 'Informative', 'Planning', 'Question'. Count how many messages fall into each category.\n\n"
        ]
        
        prompt_parts.extend(["--- CHAT LOG ---\n", chat_text, "\n--- END CHAT LOG ---\n"])
        
        if (zip_path and image_filenames) or (zip_path and video_filenames):
             prompt_parts.append("\n--- MEDIA FOR CONTEXT ---\n")

        if zip_path and image_filenames:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for filename in image_filenames:
                    mime_type = get_mime_type(filename)
                    if mime_type:
                        with zf.open(filename) as image_file:
                            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
                            prompt_parts.append(f"FILENAME: {filename}")
                            prompt_parts.append({"inline_data": {"mime_type": mime_type, "data": encoded_image}})
        
        if zip_path and video_filenames and temp_dir:
            for filename in video_filenames:
                encoded_frame = extract_frame_from_video(zip_path, filename, temp_dir)
                if encoded_frame:
                    prompt_parts.append(f"FILENAME: {filename}")
                    prompt_parts.append({"inline_data": {"mime_type": "image/jpeg", "data": encoded_frame}})

        response = model.generate_content(prompt_parts, generation_config=genai.types.GenerationConfig(response_mime_type="application/json", response_schema=json_schema))
        return json.loads(response.text)
    except Exception as e:
        error_str = str(e)
        if "API key not valid" in error_str: return {"error": "The API key is not valid. Please check your key."}
        elif "is not found for API version" in error_str: return {"error": f"The model name is incorrect or not supported. ({e})"}
        else: return {"error": f"An error occurred with the Gemini API: {e}"}

def analyse_chat_participants(messages):
    """Finds the top talker and top media sender from the messages."""
    if not messages: return None, None
    message_counts, image_counts = {}, {}
    for msg in messages:
        author = msg['author']
        if not msg['image_filename'] and not msg['video_filename']:
            message_counts[author] = message_counts.get(author, 0) + 1
        if msg['image_filename'] or msg['video_filename']:
            image_counts[author] = image_counts.get(author, 0) + 1
    top_yapper = max(message_counts, key=message_counts.get) if message_counts else "N/A"
    top_photographer = max(image_counts, key=image_counts.get) if image_counts else "N/A"
    return top_yapper, top_photographer


# --- GUI Application ---

class ChatSummarizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WhatsApp Chat Summariser")
        self.root.geometry("1400x900")
        
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind('<<Drop>>', self.handle_drop)

        self.config = configparser.ConfigParser()
        self.config_file = 'config.ini'
        self.load_config()
        
        self.temp_dir = tempfile.mkdtemp()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.dark_mode = tk.BooleanVar(value=self.detect_system_theme())
        
        self.setup_styles()
        self.setup_ui()
        self.apply_theme()
        
        self.cooldown_seconds = 10
        
        self.thumbnail_photo_images = []
        self.summary_photo_images = []
        self.graph_canvas = None
        self.resize_timer = None
        # NEW: Keep references for dynamic text wrapping and saving graphs
        self.summary_labels = []
        self.figure = None

    def _scroll_canvas(self, event, canvas):
        """Generic mousewheel scroll handler for a given canvas widget."""
        if sys.platform == "win32":
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif sys.platform == "darwin":
             canvas.yview_scroll(int(-1 * event.delta), "units")
        else:
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

    def _on_global_mousewheel(self, event):
        """Directs mouse wheel scrolling to the widget under the cursor."""
        widget_under_cursor = self.root.winfo_containing(event.x_root, event.y_root)
        if widget_under_cursor is None: return

        current_widget = widget_under_cursor
        while current_widget is not None:
            if current_widget == self.summary_canvas:
                self._scroll_canvas(event, self.summary_canvas)
                return
            if hasattr(self, 'image_canvas') and current_widget == self.image_canvas:
                self._scroll_canvas(event, self.image_canvas)
                return
            if current_widget == self.main_frame: break
            current_widget = getattr(current_widget, 'master', None)

    def detect_system_theme(self):
        """Tries to detect the system's dark mode setting on Windows."""
        saved_theme = self.config.getboolean('Settings', 'dark_mode', fallback=None)
        if saved_theme is not None: return saved_theme
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
        except (ImportError, FileNotFoundError): return False

    def setup_styles(self):
        """Defines colors and styles for light and dark modes."""
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.colors = {
            'light': {'bg': '#f0f0f0', 'fg': '#000000', 'btn_bg': '#0078D7', 'btn_fg': 'white', 'btn_active': '#005A9E', 'entry_bg': 'white', 'summary_bg': '#ffffff', 'key_msg_bg': '#e1f5fe'},
            'dark': {'bg': '#2b2b2b', 'fg': '#dcdcdc', 'btn_bg': '#005A9E', 'btn_fg': 'white', 'btn_active': '#0078D7', 'entry_bg': '#3c3c3c', 'summary_bg': '#3c3c3c', 'key_msg_bg': '#01579b'}
        }

    def apply_theme(self):
        """Applies the current theme's colors to all GUI elements."""
        theme = 'dark' if self.dark_mode.get() else 'light'
        colors = self.colors[theme]
        
        self.root.config(bg=colors['bg'])
        self.style.configure(".", background=colors['bg'], foreground=colors['fg'])
        self.style.configure("TFrame", background=colors['bg'])
        self.style.configure("TLabel", background=colors['bg'], foreground=colors['fg'])
        self.style.configure("TButton", padding=6, relief="flat", background=colors['btn_bg'], foreground=colors['fg'])
        self.style.map("TButton", background=[('active', colors['btn_active'])])
        self.style.configure("TEntry", fieldbackground=colors['entry_bg'], foreground=colors['fg'], insertcolor=colors['fg'])
        self.style.configure("TProgressbar", background=colors['btn_bg'], troughcolor=colors['bg'])
        self.style.configure("TCheckbutton", background=colors['bg'], foreground=colors['fg'])
        self.style.map('TCheckbutton', indicatorcolor=[('selected', colors['btn_bg'])])
        self.style.configure("ImageFrame.TFrame", background=colors['entry_bg'])
        
        self.style.configure("Horizontal.TScale", background=colors['bg'])
        self.style.map('Horizontal.TScale', background=[('active', colors['bg'])], troughcolor=[('!disabled', colors['entry_bg'])])
        self.slider_thumb_img = self.create_slider_thumb(colors['btn_bg'])
        self.style.element_create('custom.Scale.slider', 'image', self.slider_thumb_img, border=8, sticky='nswe')
        self.style.layout('Horizontal.TScale', [('Horizontal.Scale.trough', {'sticky': 'nswe'}), ('custom.Scale.slider', {'side': 'left', 'sticky': ''})])

        self.summary_frame.config(bg=colors['summary_bg'])
        self.summary_canvas.config(bg=colors['summary_bg'])
        self.image_canvas.config(bg=colors['entry_bg'])
        
        for child in self.summary_frame.winfo_children():
            if isinstance(child, (tk.Label, tk.Frame)):
                child.config(bg=colors['summary_bg'])
                for grandchild in child.winfo_children():
                     if isinstance(grandchild, tk.Label): grandchild.config(bg=colors['summary_bg'])
        
        for child in self.image_frame.winfo_children():
            if isinstance(child, tk.Label): child.config(bg=colors['entry_bg'])
            
        if self.all_messages and self.last_summary_data:
            self.display_graphs(self.all_messages, self.last_summary_data)


    def create_slider_thumb(self, color):
        """Creates a circular image to use as the slider's handle."""
        image = Image.new('RGBA', (16, 16), (0,0,0,0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        draw.ellipse((0, 0, 15, 15), fill=color)
        return ImageTk.PhotoImage(image)

    def toggle_dark_mode(self):
        """Applies the new theme and saves the setting."""
        self.apply_theme()
        if 'Settings' not in self.config: self.config.add_section('Settings')
        self.config.set('Settings', 'dark_mode', str(self.dark_mode.get()))
        with open(self.config_file, 'w') as configfile: self.config.write(configfile)

    def load_config(self):
        """Loads settings from config.ini."""
        self.config.read(self.config_file)
        if 'API' not in self.config: self.config['API'] = {'key': ''}
        if 'Settings' not in self.config: self.config['Settings'] = {'remember_key': 'False', 'dark_mode': 'False'}

    def save_api_key(self):
        """Saves the API key and preference to the config file."""
        self.config['API']['key'] = self.api_key_entry.get() if self.remember_api_key_var.get() else ''
        self.config['Settings']['remember_key'] = str(self.remember_api_key_var.get())
        with open(self.config_file, 'w') as configfile: self.config.write(configfile)
    
    def on_closing(self):
        """Cleans up and closes the application."""
        import shutil
        shutil.rmtree(self.temp_dir)
        self.root.destroy()

    def setup_ui(self):
        """Creates and lays out all the widgets in the main window."""
        self.main_frame = ttk.Frame(self.root, padding="20")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.controls_frame = ttk.Frame(self.main_frame)
        self.controls_frame.pack(fill=tk.X, pady=(0, 10), expand=False)
        self.controls_frame.columnconfigure(1, weight=1)

        self.file_path_label = ttk.Label(self.controls_frame, text="Drop .zip file here or click Import", wraplength=400, anchor="center")
        self.file_path_label.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.import_button = ttk.Button(self.controls_frame, text="Import Chat (.zip)", command=self.select_file)
        self.import_button.grid(row=0, column=0, sticky="w")

        ttk.Label(self.controls_frame, text="Gemini API Key:").grid(row=1, column=0, sticky="w", pady=(10,0))
        self.api_key_entry = ttk.Entry(self.controls_frame, show="*")
        self.api_key_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(10,0))
        self.api_key_entry.insert(0, self.config['API']['key'])
        
        settings_frame = ttk.Frame(self.controls_frame)
        settings_frame.grid(row=2, column=1, sticky='ew', padx=(10,0), pady=(5,0))

        detail_frame = ttk.Frame(settings_frame)
        detail_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(detail_frame, text="Brief").pack(side=tk.LEFT, padx=(0,5))
        self.detail_var = tk.IntVar(value=1)
        self.detail_slider = ttk.Scale(detail_frame, from_=0, to=2, variable=self.detail_var, orient='horizontal', command=lambda s: self.detail_var.set(round(float(s))))
        self.detail_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(detail_frame, text="Verbose").pack(side=tk.LEFT, padx=(5,0))

        checkbox_frame = ttk.Frame(settings_frame)
        checkbox_frame.pack(side=tk.LEFT, padx=(20,0))
        self.remember_api_key_var = tk.BooleanVar(value=self.config.getboolean('Settings', 'remember_key', fallback=False))
        self.remember_checkbox = ttk.Checkbutton(checkbox_frame, text="Remember API Key", variable=self.remember_api_key_var, command=self.save_api_key)
        self.remember_checkbox.pack(side=tk.LEFT, padx=(0, 10))
        self.dark_mode_checkbox = ttk.Checkbutton(checkbox_frame, text="Dark Mode", variable=self.dark_mode, command=self.toggle_dark_mode)
        self.dark_mode_checkbox.pack(side=tk.LEFT, padx=(0,10))
        self.include_images_var = tk.BooleanVar(value=True)
        self.image_checkbox = ttk.Checkbutton(checkbox_frame, text="Include Media", variable=self.include_images_var, command=self.toggle_media_count_menu)
        self.image_checkbox.pack(side=tk.LEFT)

        options_frame = ttk.Frame(self.controls_frame)
        options_frame.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(10,0))
        options_frame.columnconfigure(1, weight=1)
        options_frame.columnconfigure(3, weight=1)

        ttk.Label(options_frame, text="Summarise Period:").grid(row=0, column=0, sticky="w")
        self.time_range_var = tk.StringVar(value="All time")
        time_options = ["Last 24 hours", "Last 7 days", "Last 30 days", "All time"]
        self.time_range_menu = ttk.OptionMenu(options_frame, self.time_range_var, time_options[3], *time_options)
        self.time_range_menu.grid(row=0, column=1, sticky="ew", padx=(10, 20))

        ttk.Label(options_frame, text="Recent Media:").grid(row=0, column=2, sticky="w")
        self.media_count_var = tk.StringVar(value="0")
        self.media_count_menu = ttk.OptionMenu(options_frame, self.media_count_var, "0")
        self.media_count_menu.grid(row=0, column=3, sticky="ew", padx=(10, 0))

        self.summarize_button = ttk.Button(self.main_frame, text="Generate Summary", command=self.start_summary_thread)
        self.summarize_button.pack(fill=tk.X, pady=10, expand=False)
        self.progress_bar = ttk.Progressbar(self.main_frame, mode='indeterminate')
        
        # MODIFIED: Use a main frame with pack for layout control
        content_frame = ttk.Frame(self.main_frame)
        content_frame.pack(fill="both", expand=True, pady=(0, 10))

        # MODIFIED: Image preview frame is now packed to the left with a fixed width
        self.image_preview_frame = ttk.Frame(content_frame, width=140)
        self.image_preview_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        self.image_preview_frame.pack_propagate(False) # Prevents frame from shrinking
        self.image_canvas = tk.Canvas(self.image_preview_frame, relief="solid", borderwidth=1)
        img_scrollbar = ttk.Scrollbar(self.image_preview_frame, orient="vertical", command=self.image_canvas.yview)
        self.image_frame = ttk.Frame(self.image_canvas, style="ImageFrame.TFrame")
        self.image_canvas.create_window((0, 0), window=self.image_frame, anchor="nw")
        self.image_canvas.configure(yscrollcommand=img_scrollbar.set)
        img_scrollbar.pack(side="right", fill="y")
        self.image_canvas.pack(side="left", fill="both", expand=True)
        self.image_frame.bind("<Configure>", lambda e: self.image_canvas.configure(scrollregion=self.image_canvas.bbox("all")))

        # MODIFIED: PanedWindow now only contains the resizable summary and graph panes
        content_pane = ttk.PanedWindow(content_frame, orient=tk.HORIZONTAL)
        content_pane.pack(side=tk.LEFT, fill="both", expand=True)

        self.summary_container = ttk.Frame(content_pane)
        self.summary_canvas = tk.Canvas(self.summary_container, relief="solid", borderwidth=1)
        summary_scrollbar = ttk.Scrollbar(self.summary_container, orient="vertical", command=self.summary_canvas.yview)
        self.summary_frame = tk.Frame(self.summary_canvas)
        summary_scrollbar.pack(side="right", fill="y")
        self.summary_canvas.pack(side="left", fill="both", expand=True)
        self.summary_canvas.create_window((0, 0), window=self.summary_frame, anchor="nw")
        self.summary_canvas.configure(yscrollcommand=summary_scrollbar.set)
        self.summary_frame.bind("<Configure>", lambda e: self.summary_canvas.configure(scrollregion=self.summary_canvas.bbox("all")))
        # NEW: Bind resize event to update text wrapping
        self.summary_canvas.bind("<Configure>", self.on_summary_canvas_resize)

        self.graphs_frame = ttk.Frame(content_pane)
        self.graphs_frame.bind("<Configure>", self.on_graph_frame_resize)

        content_pane.add(self.summary_container, weight=3)
        content_pane.add(self.graphs_frame, weight=2)

        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=5)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.chat_file_path, self.all_messages, self.image_list, self.video_list, self.last_summary_data = None, [], [], [], None
        self.toggle_media_count_menu()

        self.root.bind_all("<MouseWheel>", self._on_global_mousewheel)
        self.root.bind_all("<Button-4>", self._on_global_mousewheel)
        self.root.bind_all("<Button-5>", self._on_global_mousewheel)

        # NEW: Setup right-click menu for graphs
        self.graph_context_menu = tk.Menu(self.root, tearoff=0)
        self.graph_context_menu.add_command(label="Save Image...", command=self.save_graphs)

    # --- NEW and MODIFIED: UI Behavior and Graphing Functions ---
    def on_summary_canvas_resize(self, event):
        """Updates the wraplength of all labels in the summary frame."""
        # Update the scroll region
        self.summary_canvas.configure(scrollregion=self.summary_canvas.bbox("all"))
        # Update text wrapping
        width = event.width - 20  # Subtract padding
        for label in self.summary_labels:
            label.config(wraplength=width)

    def on_graph_frame_resize(self, event):
        """Debounces resize events to redraw graphs efficiently."""
        if self.resize_timer:
            self.root.after_cancel(self.resize_timer)
        self.resize_timer = self.root.after(250, self.redraw_graphs)

    def redraw_graphs(self):
        """Helper function to call the main graph display function."""
        if self.all_messages and self.last_summary_data:
            self.display_graphs(self.all_messages, self.last_summary_data)

    def show_graph_context_menu(self, event):
        """Displays the right-click context menu for the graph canvas."""
        if self.figure:
            self.graph_context_menu.post(event.x_root, event.y_root)
            
    def save_graphs(self):
        """Opens a file dialog to save the current graph figure."""
        if not self.figure:
            messagebox.showwarning("No Graph", "There is no graph to save.")
            return
        
        filepath = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("JPEG Image", "*.jpg"), ("All Files", "*.*")],
            title="Save Graph Image"
        )
        if not filepath:
            return
        try:
            self.figure.savefig(filepath, dpi=300)
            self.status_var.set(f"Graph saved to {os.path.basename(filepath)}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save graph: {e}")

    def display_graphs(self, messages, summary_data):
        """Clears old graphs and displays new ones, sized to the container."""
        if self.graph_canvas:
            self.graph_canvas.get_tk_widget().destroy()

        if self.graphs_frame.winfo_width() <= 1 or self.graphs_frame.winfo_height() <= 1:
            return
            
        theme = 'dark' if self.dark_mode.get() else 'light'
        bg_color = self.colors[theme]['bg']
        fg_color = self.colors[theme]['fg']
        
        dpi = 100
        width_inches = self.graphs_frame.winfo_width() / dpi
        height_inches = self.graphs_frame.winfo_height() / dpi

        # MODIFIED: Store figure in self.figure
        self.figure = Figure(figsize=(width_inches, height_inches), dpi=dpi, facecolor=bg_color)
        
        ax1 = self.figure.add_subplot(311)
        self.plot_message_distribution(ax1, messages, fg_color)
        
        ax2 = self.figure.add_subplot(312)
        self.plot_activity_heatmap(ax2, messages, fg_color)

        ax3 = self.figure.add_subplot(313)
        self.plot_sentiments(ax3, summary_data, fg_color)

        self.figure.tight_layout(pad=2.0)

        self.graph_canvas = FigureCanvasTkAgg(self.figure, master=self.graphs_frame)
        self.graph_canvas.draw()
        widget = self.graph_canvas.get_tk_widget()
        widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # NEW: Bind right-click event to the new canvas widget
        widget.bind("<Button-3>", self.show_graph_context_menu)

    def plot_message_distribution(self, ax, messages, fg_color):
        """Plots a pie chart of messages sent by each author."""
        authors = [msg['author'] for msg in messages]
        author_counts = pd.Series(authors).value_counts()
        
        threshold = 0.10 * len(messages)
        main_authors = author_counts[author_counts >= threshold]
        other_count = author_counts[author_counts < threshold].sum()
        if other_count > 0:
            main_authors['Other'] = other_count
            
        ax.pie(main_authors, labels=main_authors.index, autopct='%1.1f%%', startangle=90, textprops={'color': fg_color})
        ax.set_title('Message Distribution', color=fg_color)
        ax.axis('equal')

    def plot_activity_heatmap(self, ax, messages, fg_color):
        """Plots a heatmap of message activity by day and hour."""
        df = pd.DataFrame(messages)
        df['hour'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.day_name()
        
        activity = df.groupby(['hour', 'day_of_week']).size().unstack(fill_value=0)
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        activity = activity.reindex(columns=days)
        
        ax.imshow(activity, cmap='viridis', aspect='auto')
        ax.set_xticks(np.arange(len(days)))
        ax.set_xticklabels(days, rotation=45, ha="right", color=fg_color)
        ax.set_yticks(np.arange(24))
        ax.set_yticklabels(np.arange(24), color=fg_color)
        ax.set_title('Message Activity Heatmap', color=fg_color)
        
    def plot_sentiments(self, ax, summary_data, fg_color):
        """Plots a bar chart of message sentiments."""
        sentiments = summary_data.get('sentiments', [])
        if sentiments:
            df = pd.DataFrame(sentiments).sort_values('count', ascending=False)
            ax.bar(df['sentiment'], df['count'], color='#0078D7')
        
        ax.set_title('Message Sentiments', color=fg_color)
        ax.tick_params(axis='x', labelrotation=45, colors=fg_color)
        ax.tick_params(axis='y', colors=fg_color)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color(fg_color)
        ax.spines['left'].set_color(fg_color)

    def toggle_media_count_menu(self):
        """Enables/disables the media count dropdown."""
        total_media = len(self.image_list) + len(self.video_list)
        if self.include_images_var.get() and total_media > 0:
            self.media_count_menu.config(state=tk.NORMAL)
        else:
            self.media_count_menu.config(state=tk.DISABLED)
            
    def update_media_count_menu(self):
        """Populates the media count dropdown."""
        total_media = len(self.image_list) + len(self.video_list)
        menu = self.media_count_menu["menu"]
        menu.delete(0, "end")

        if total_media == 0:
            self.media_count_var.set("0")
            menu.add_command(label="0", command=tk._setit(self.media_count_var, "0"))
        else:
            options = list(range(1, total_media + 1))
            default_val = str(min(15, total_media))
            self.media_count_var.set(default_val)
            for option in options:
                menu.add_command(label=str(option), command=tk._setit(self.media_count_var, str(option)))
        
        self.toggle_media_count_menu()

    def handle_drop(self, event):
        """Handles a file drop event."""
        filepath = event.data.strip('{}')
        if filepath.lower().endswith('.zip'): self.process_file(filepath)
        else: messagebox.showwarning("Invalid File", "Please drop a .zip file.")

    def select_file(self):
        """Opens a file dialog to select a chat zip file."""
        path = filedialog.askopenfilename(title="Select WhatsApp Chat ZIP File", filetypes=(("Zip files", "*.zip"),))
        if path: self.process_file(path)

    def process_file(self, path):
        """Parses the selected file and updates the GUI."""
        self.chat_file_path = path
        self.file_path_label.config(text=os.path.basename(path))
        self.status_var.set("File selected. Parsing messages...")
        self.root.update_idletasks()
        self.all_messages, self.image_list, self.video_list = parse_whatsapp_zip(self.chat_file_path)
        
        if not self.all_messages:
             messagebox.showwarning("Parsing Issue", "No messages could be parsed.")
             self.status_var.set("Parsing failed.")
        else:
            self.status_var.set(f"Successfully parsed {len(self.all_messages)} messages.")
            self.update_media_count_menu()
            self.display_media_thumbnails()
            if self.graph_canvas:
                self.graph_canvas.get_tk_widget().destroy()
                self.graph_canvas = None


    def open_media_external(self, media_name):
        """Extracts and opens a media file with the default viewer."""
        if not self.chat_file_path: return
        try:
            with zipfile.ZipFile(self.chat_file_path, 'r') as zf:
                extracted_path = zf.extract(media_name, path=self.temp_dir)
                if sys.platform == "win32": os.startfile(extracted_path)
                else: subprocess.call(["open" if sys.platform == "darwin" else "xdg-open", extracted_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open media: {e}")

    def display_media_thumbnails(self):
        """Creates and shows clickable thumbnails for all media."""
        for widget in self.image_frame.winfo_children(): widget.destroy()
        self.thumbnail_photo_images.clear()
        if not self.chat_file_path: return

        try:
            with zipfile.ZipFile(self.chat_file_path, 'r') as zf:
                for img_name in self.image_list:
                    with zf.open(img_name) as image_file:
                        img = Image.open(io.BytesIO(image_file.read()))
                        img.thumbnail((100, 100))
                        photo_img = ImageTk.PhotoImage(img)
                        self.thumbnail_photo_images.append(photo_img)
                        img_label = tk.Label(self.image_frame, image=photo_img, bg=self.colors['dark' if self.dark_mode.get() else 'light']['entry_bg'], cursor="hand2")
                        img_label.pack(side=tk.TOP, padx=5, pady=5)
                        img_label.bind("<Button-1>", lambda e, name=img_name: self.open_media_external(name))
                for vid_name in self.video_list:
                    thumb_img = extract_frame_from_video(self.chat_file_path, vid_name, self.temp_dir, as_thumbnail=True)
                    if thumb_img:
                        photo_img = ImageTk.PhotoImage(thumb_img)
                        self.thumbnail_photo_images.append(photo_img)
                        vid_label = tk.Label(self.image_frame, image=photo_img, bg=self.colors['dark' if self.dark_mode.get() else 'light']['entry_bg'], cursor="hand2")
                        vid_label.pack(side=tk.TOP, padx=5, pady=5)
                        vid_label.bind("<Button-1>", lambda e, name=vid_name: self.open_media_external(name))
        except Exception as e:
            self.status_var.set(f"Error loading thumbnails: {e}")

    def start_summary_thread(self):
        """Validates input and starts the background summarisation process."""
        if not self.chat_file_path: messagebox.showwarning("No File", "Please import a chat zip file first."); return
        if not self.api_key_entry.get(): messagebox.showwarning("No API Key", "Please enter your Gemini API key."); return
        
        self.save_api_key()
        self.summarize_button.config(state=tk.DISABLED)
        self.status_var.set("Summarising... This may take a moment.")
        self.progress_bar.pack(fill=tk.X, pady=(5,10), expand=False)
        self.progress_bar.start(10)
        
        thread = threading.Thread(target=self.run_summarisation)
        thread.daemon = True
        thread.start()

    def run_summarisation(self):
        """Prepares data and calls the Gemini API in a background thread."""
        summary_data = None
        try:
            time_range = self.time_range_var.get()
            filtered_messages = filter_messages_by_time(self.all_messages, time_range)
            
            if not filtered_messages:
                summary_data = {"error": "No messages found in the selected time frame."}
            else:
                chat_text_for_ai = format_chat_for_summary(filtered_messages)
                api_key = self.api_key_entry.get()
                detail_level = self.detail_var.get()
                
                image_filenames_to_send, video_filenames_to_send = [], []
                if self.include_images_var.get():
                    try:
                        num_media_to_include = int(self.media_count_var.get())
                        media_messages = [msg for msg in filtered_messages if msg['image_filename'] or msg['video_filename']]
                        most_recent_media_messages = media_messages[-num_media_to_include:]
                        
                        image_filenames_to_send = list(set(msg['image_filename'] for msg in most_recent_media_messages if msg['image_filename']))
                        video_filenames_to_send = list(set(msg['video_filename'] for msg in most_recent_media_messages if msg['video_filename']))
                    except (ValueError, TypeError):
                        image_filenames_to_send, video_filenames_to_send = [], []
                
                summary_data = get_summary_from_gemini(api_key, chat_text_for_ai, detail_level, self.chat_file_path, image_filenames_to_send, video_filenames_to_send, self.temp_dir)
                self.last_summary_data = summary_data 
                
                if summary_data and 'error' not in summary_data:
                    top_yapper, top_photographer = analyse_chat_participants(filtered_messages)
                    summary_data['top_yapper'] = top_yapper
                    summary_data['top_photographer'] = top_photographer
                    self.root.after(0, self.display_graphs, filtered_messages, summary_data)

        except Exception as e:
            self.root.after(0, messagebox.showerror, "Error", f"An unexpected error occurred: {e}")
            summary_data = {"error": "An error occurred during summarisation."}
        finally:
            self.root.after(0, self.display_structured_summary, summary_data)
            self.root.after(0, self.finalize_summary_ui)

    def load_media_for_summary(self, filename):
        """Loads a media file from the zip for inline display."""
        if not self.chat_file_path: return None
        try:
            with zipfile.ZipFile(self.chat_file_path, 'r') as zf:
                if filename in self.image_list:
                    with zf.open(filename) as image_file:
                        img = Image.open(io.BytesIO(image_file.read()))
                        img.thumbnail((500, 500))
                        return ImageTk.PhotoImage(img)
                elif filename in self.video_list:
                    pil_img = extract_frame_from_video(self.chat_file_path, filename, self.temp_dir, as_thumbnail=False)
                    if pil_img:
                        img_data = base64.b64decode(pil_img)
                        img = Image.open(io.BytesIO(img_data))
                        img.thumbnail((500, 500))
                        return ImageTk.PhotoImage(img)
        except Exception:
            return None
        return None

    def display_structured_summary(self, data):
        """Builds the summary view from the structured JSON data."""
        for widget in self.summary_frame.winfo_children(): widget.destroy()
        self.summary_photo_images.clear()
        # NEW: Clear the list of labels for wrapping
        self.summary_labels.clear()
        theme = 'dark' if self.dark_mode.get() else 'light'
        colors = self.colors[theme]

        if not data or 'error' in data:
            error_msg = data.get('error', 'An unknown error occurred.')
            label = tk.Label(self.summary_frame, text=error_msg, justify="left", bg=colors['summary_bg'], fg='red', font=('Helvetica', 10))
            label.pack(pady=10, padx=10, anchor='w')
            self.summary_labels.append(label)
            return

        for part in data.get('summary_parts', []):
            part_type = part.get('type')
            
            if part_type == 'key_message':
                author, content = part.get('author', 'System'), part.get('content', '')
                key_msg_frame = tk.Frame(self.summary_frame, bg=colors['key_msg_bg'], relief="solid", borderwidth=1)
                key_msg_frame.pack(pady=10, padx=10, fill='x')
                author_label = tk.Label(key_msg_frame, text=f"{author} said:", justify="left", bg=colors['key_msg_bg'], fg=colors['fg'], font=('Helvetica', 9, 'italic'))
                author_label.pack(pady=(5, 0), padx=10, anchor='w')
                content_label = tk.Label(key_msg_frame, text=content, justify="left", bg=colors['key_msg_bg'], fg=colors['fg'], font=('Helvetica', 12, 'bold'))
                content_label.pack(pady=(0, 5), padx=10, anchor='w')
                # Add labels to the list for wrapping
                self.summary_labels.append(author_label)
                self.summary_labels.append(content_label)
            
            elif part_type == 'media':
                filename = part.get('filename')
                if filename:
                    media_photo = self.load_media_for_summary(filename)
                    if media_photo:
                        self.summary_photo_images.append(media_photo)
                        img_label = tk.Label(self.summary_frame, image=media_photo, bg=colors['summary_bg'])
                        img_label.pack(pady=10, padx=10)

            else:
                content = part.get('content', '')
                content_label = tk.Label(self.summary_frame, text=content, justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 10))
                content_label.pack(pady=5, padx=10, anchor='w')
                self.summary_labels.append(content_label)

        bullets = data.get('bullet_points', [])
        if bullets:
            title = tk.Label(self.summary_frame, text="Key Points:", justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 11, 'bold'))
            title.pack(pady=(15, 5), padx=10, anchor='w')
            self.summary_labels.append(title)
            for point in bullets:
                bullet = tk.Label(self.summary_frame, text=f"• {point}", justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 10))
                bullet.pack(pady=2, padx=20, anchor='w')
                self.summary_labels.append(bullet)
        
        analysis_title = tk.Label(self.summary_frame, text="Chat Analysis:", justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 11, 'bold'))
        analysis_title.pack(pady=(15, 5), padx=10, anchor='w')
        self.summary_labels.append(analysis_title)
        
        table_frame = tk.Frame(self.summary_frame, bg=colors['summary_bg'])
        table_frame.pack(pady=5, padx=20, anchor='w')
        tk.Label(table_frame, text="Top Yapper:", font=('Helvetica', 10, 'bold'), bg=colors['summary_bg'], fg=colors['fg']).grid(row=0, column=0, sticky='w', padx=(0,10))
        tk.Label(table_frame, text=data.get('top_yapper', 'N/A'), font=('Helvetica', 10), bg=colors['summary_bg'], fg=colors['fg']).grid(row=0, column=1, sticky='w')
        tk.Label(table_frame, text="Top Photographer:", font=('Helvetica', 10, 'bold'), bg=colors['summary_bg'], fg=colors['fg']).grid(row=1, column=0, sticky='w', padx=(0,10))
        tk.Label(table_frame, text=data.get('top_photographer', 'N/A'), font=('Helvetica', 10), bg=colors['summary_bg'], fg=colors['fg']).grid(row=1, column=1, sticky='w')
        
        self.status_var.set("Summary generated successfully.")
        
        # Trigger a configure event to set initial wrapping
        self.on_summary_canvas_resize(tk.Event())
        
    def finalize_summary_ui(self):
        """Hides the progress bar and starts the button cooldown."""
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.start_cooldown()

    def start_cooldown(self):
        """Disables the generate button and begins the cooldown timer."""
        self.summarize_button.config(state=tk.DISABLED)
        self.update_cooldown(self.cooldown_seconds)

    def update_cooldown(self, seconds_left):
        """Updates the button text with a countdown each second."""
        if seconds_left > 0:
            self.summarize_button.config(text=f"Please wait ({seconds_left}s)")
            self.root.after(1000, self.update_cooldown, seconds_left - 1)
        else:
            self.summarize_button.config(text="Generate Summary", state=tk.NORMAL)


if __name__ == "__main__":
    # To run this code, you need to install:
    # pip install google-generativeai tkinterdnd2 pillow opencv-python pandas matplotlib
    
    root = TkinterDnD.Tk()
    app = ChatSummarizerApp(root)
    root.mainloop()
