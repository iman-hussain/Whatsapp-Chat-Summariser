# Import necessary libraries for the application
import tkinter as tk  # For creating the graphical user interface (GUI)
from tkinter import filedialog, ttk, messagebox  # Specific GUI components and dialogs
import re  # For regular expressions, used to parse the chat text
from datetime import datetime, timedelta  # For handling dates and times
import google.generativeai as genai  # The Google Gemini API library
import threading  # To run the API call in the background and keep the GUI responsive
import zipfile  # To handle .zip files from WhatsApp exports with media
import io  # To handle the chat file as a text stream from the zip
import base64  # To encode images for the API
import os  # To work with file paths and extensions
import configparser # To save and load the API key
from tkinterdnd2 import DND_FILES, TkinterDnD # For drag-and-drop functionality
from PIL import Image, ImageTk # For handling and displaying image thumbnails
import json # To handle the structured JSON response from the API
import tempfile # To temporarily store images for viewing
import subprocess # To open files with the default system application
import sys # To check the operating system
import cv2 # OpenCV for video processing
import numpy as np # Required by OpenCV

# --- Core Functions ---

def get_mime_type(filename):
    """Gets the MIME type from a filename extension."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in ['.jpg', '.jpeg']: return 'image/jpeg'
    elif ext == '.png': return 'image/png'
    elif ext == '.webp': return 'image/webp'
    return None

def parse_whatsapp_zip(zip_path):
    """Parses an exported WhatsApp .zip chat archive."""
    messages, image_list, video_list = [], [], []
    media_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.mp4')
    pattern = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4}, \d{2}:\d{2}) - (.*?): (.*?)(?:\s*\(file attached\))?$")

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            chat_filename = next((name for name in zf.namelist() if name.endswith('.txt')), None)
            if not chat_filename: raise FileNotFoundError("Could not find a .txt chat file in the zip archive.")
            
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
    """Filters messages based on the selected time range."""
    if not messages: return []
    now = datetime.now()
    time_deltas = {"Last 24 hours": timedelta(days=1), "Last 7 days": timedelta(days=7), "Last 30 days": timedelta(days=30)}
    if time_range_str == "All time": return messages
    if time_range_str in time_deltas:
        start_time = now - time_deltas[time_range_str]
        return [msg for msg in messages if msg['timestamp'] >= start_time]
    return []

def format_chat_for_summary(messages):
    """Formats a list of message dictionaries into a single string for the AI."""
    formatted_lines = []
    for msg in messages:
        if msg['image_filename']: text = f"[Image Sent: {msg['image_filename']}]"
        elif msg['video_filename']: text = f"[Video Sent: {msg['video_filename']}]"
        else: text = msg['message']
        formatted_lines.append(f"[{msg['timestamp'].strftime('%Y-%m-%d %H:%M')}] {msg['author']}: {text}")
    return "\n".join(formatted_lines)

def extract_frame_from_video(zip_path, video_filename, temp_dir, as_thumbnail=False):
    """Extracts a frame from a video file inside a zip archive at the 10% mark."""
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
    """Uses the Gemini API to get a structured summary of the chat."""
    if not api_key: raise ValueError("API key is missing.")
    if not chat_text: return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # UPDATED SCHEMA: Added 'media' type and 'filename' property
        json_schema = {
            "type": "object",
            "properties": {
                "summary_parts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["text", "key_message", "media"]},
                            "content": {"type": "string"},
                            "author": {"type": "string"},
                            "filename": {"type": "string"}
                        },
                        "required": ["type"]
                    }
                },
                "bullet_points": {"type": "array", "items": {"type": "string"}}
            }
        }
        
        # UPDATED DETAIL MAP: Made brief more brief and verbose more verbose
        detail_map = {
            0: "a single sentence summary, capturing only the absolute main topic",
            1: "a standard, medium-detail summary",
            2: "an extremely verbose and comprehensive, almost minute-by-minute summary. Capture as many details, nuances, specific examples, jokes, and conversational turns as possible. Be exhaustive"
        }
        detail_text = detail_map.get(detail_level, "a standard, medium-detail summary")
        
        prompt_parts = [
            f"Analyse the following WhatsApp chat log. Provide a structured, {detail_text} summary in JSON format. ",
            "The summary should be broken into parts. Most parts should be of type 'text'. ",
            "Identify 1-3 particularly important or representative 'key_message's. Ensure these are from a variety of different authors if possible, not just one person. ",
            "For each part, provide the content and the author. For general summary text, the author can be 'narrator'. ",
            "Crucially, be specific in your summary. Use the names of the people involved (e.g., 'Simon and Luke discussed...') instead of generic phrases like 'the chat says' or 'the users talked about'. ",
            # UPDATED PROMPT: Added instruction for inline media
            "If you discuss a specific image or video, instead of describing it in a 'text' part, create a 'media' part and set its 'filename' property to the corresponding filename provided with the media. Then continue the summary in a new 'text' part.",
            "Finally, provide a list of key 'bullet_points'.\n\n"
        ]
        
        prompt_parts.extend(["--- CHAT LOG ---\n", chat_text, "\n--- END CHAT LOG ---\n"])
        
        # UPDATED PROMPT: Added context for media files
        if (zip_path and image_filenames) or (zip_path and video_filenames):
             prompt_parts.append("\n--- MEDIA FOR CONTEXT ---\n")

        if zip_path and image_filenames:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for filename in image_filenames:
                    mime_type = get_mime_type(filename)
                    if mime_type:
                        with zf.open(filename) as image_file:
                            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
                            # Add filename before the data for the AI to associate them
                            prompt_parts.append(f"FILENAME: {filename}")
                            prompt_parts.append({"inline_data": {"mime_type": mime_type, "data": encoded_image}})
        
        if zip_path and video_filenames and temp_dir:
            for filename in video_filenames:
                encoded_frame = extract_frame_from_video(zip_path, filename, temp_dir)
                if encoded_frame:
                    # Add filename before the data for the AI to associate them
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
    """Analyses the chat messages to find the top talker and photographer."""
    if not messages: return None, None
    message_counts, image_counts = {}, {}
    for msg in messages:
        author = msg['author']
        # Increment message count for the author (excluding media messages for 'yapper' award)
        if not msg['image_filename'] and not msg['video_filename']:
            message_counts[author] = message_counts.get(author, 0) + 1
        # Increment media count if an image or video was sent
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
        self.root.geometry("800x900")
        
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
        
        # Lists to hold references to images to prevent garbage collection
        self.thumbnail_photo_images = []
        self.summary_photo_images = []


    def detect_system_theme(self):
        """Detects if the system (Windows) is in dark mode."""
        saved_theme = self.config.getboolean('Settings', 'dark_mode', fallback=None)
        if saved_theme is not None: return saved_theme
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
        except (ImportError, FileNotFoundError): return False

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.colors = {
            'light': {'bg': '#f0f0f0', 'fg': '#000000', 'btn_bg': '#0078D7', 'btn_fg': 'white', 'btn_active': '#005A9E', 'entry_bg': 'white', 'summary_bg': '#ffffff', 'key_msg_bg': '#e1f5fe'},
            'dark': {'bg': '#2b2b2b', 'fg': '#dcdcdc', 'btn_bg': '#005A9E', 'btn_fg': 'white', 'btn_active': '#0078D7', 'entry_bg': '#3c3c3c', 'summary_bg': '#3c3c3c', 'key_msg_bg': '#01579b'}
        }

    def apply_theme(self):
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
        self.image_canvas.config(bg=colors['entry_bg'])
        
        for child in self.summary_frame.winfo_children():
            if isinstance(child, (tk.Label, tk.Frame)):
                child.config(bg=colors['summary_bg'])
                for grandchild in child.winfo_children():
                     if isinstance(grandchild, tk.Label): grandchild.config(bg=colors['summary_bg'])
        
        for child in self.image_frame.winfo_children():
            if isinstance(child, tk.Label): child.config(bg=colors['entry_bg'])

    def create_slider_thumb(self, color):
        """Creates an image for the slider thumb."""
        image = Image.new('RGBA', (16, 16), (0,0,0,0))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        draw.ellipse((0, 0, 15, 15), fill=color)
        return ImageTk.PhotoImage(image)

    def toggle_dark_mode(self):
        self.apply_theme()
        if 'Settings' not in self.config: self.config.add_section('Settings')
        self.config.set('Settings', 'dark_mode', str(self.dark_mode.get()))
        with open(self.config_file, 'w') as configfile: self.config.write(configfile)

    def load_config(self):
        self.config.read(self.config_file)
        if 'API' not in self.config: self.config['API'] = {'key': ''}
        if 'Settings' not in self.config: self.config['Settings'] = {'remember_key': 'False', 'dark_mode': 'False'}

    def save_api_key(self):
        self.config['API']['key'] = self.api_key_entry.get() if self.remember_api_key_var.get() else ''
        self.config['Settings']['remember_key'] = str(self.remember_api_key_var.get())
        with open(self.config_file, 'w') as configfile: self.config.write(configfile)
    
    def on_closing(self):
        import shutil
        shutil.rmtree(self.temp_dir)
        self.root.destroy()

    def setup_ui(self):
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
        self.image_checkbox = ttk.Checkbutton(checkbox_frame, text="Include Media", variable=self.include_images_var)
        self.image_checkbox.pack(side=tk.LEFT)

        ttk.Label(self.controls_frame, text="Summarise Period:").grid(row=3, column=0, sticky="w", pady=(10,0))
        self.time_range_var = tk.StringVar(value="All time")
        time_options = ["Last 24 hours", "Last 7 days", "Last 30 days", "All time"]
        self.time_range_menu = ttk.OptionMenu(self.controls_frame, self.time_range_var, time_options[3], *time_options)
        self.time_range_menu.grid(row=3, column=1, sticky="ew", padx=(10, 0), pady=(10,0))

        self.summarize_button = ttk.Button(self.main_frame, text="Generate Summary", command=self.start_summary_thread)
        self.summarize_button.pack(fill=tk.X, pady=10, expand=False)
        self.progress_bar = ttk.Progressbar(self.main_frame, mode='indeterminate')
        
        self.summary_container = ttk.Frame(self.main_frame)
        self.summary_container.pack(side="top", fill="both", expand=True, pady=(0, 10))
        
        summary_canvas = tk.Canvas(self.summary_container, relief="solid", borderwidth=1)
        summary_scrollbar = ttk.Scrollbar(self.summary_container, orient="vertical", command=summary_canvas.yview)
        self.summary_frame = tk.Frame(summary_canvas)
        
        summary_scrollbar.pack(side="right", fill="y")
        summary_canvas.pack(side="left", fill="both", expand=True)
        
        summary_canvas.create_window((0, 0), window=self.summary_frame, anchor="nw")
        summary_canvas.configure(yscrollcommand=summary_scrollbar.set)
        self.summary_frame.bind("<Configure>", lambda e: summary_canvas.configure(scrollregion=summary_canvas.bbox("all")))

        self.image_preview_frame = ttk.Frame(self.main_frame)
        self.image_preview_frame.pack(fill="x", expand=False)
        
        self.image_canvas = tk.Canvas(self.image_preview_frame, relief="solid", borderwidth=1, height=120)
        img_scrollbar = ttk.Scrollbar(self.image_preview_frame, orient="horizontal", command=self.image_canvas.xview)
        self.image_frame = ttk.Frame(self.image_canvas, style="ImageFrame.TFrame")

        self.image_canvas.create_window((0, 0), window=self.image_frame, anchor="nw")
        self.image_canvas.configure(xscrollcommand=img_scrollbar.set)

        img_scrollbar.pack(side="bottom", fill="x")
        self.image_canvas.pack(side="top", fill="x", expand=True)
        
        self.image_frame.bind("<Configure>", lambda e: self.image_canvas.configure(scrollregion=self.image_canvas.bbox("all")))

        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=5)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.chat_file_path, self.all_messages, self.image_list, self.video_list = None, [], [], []

    def handle_drop(self, event):
        filepath = event.data.strip('{}')
        if filepath.lower().endswith('.zip'): self.process_file(filepath)
        else: messagebox.showwarning("Invalid File", "Please drop a .zip file.")

    def select_file(self):
        path = filedialog.askopenfilename(title="Select WhatsApp Chat ZIP File", filetypes=(("Zip files", "*.zip"),))
        if path: self.process_file(path)

    def process_file(self, path):
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
            self.display_media_thumbnails()

    def open_media_external(self, media_name):
        if not self.chat_file_path: return
        try:
            with zipfile.ZipFile(self.chat_file_path, 'r') as zf:
                extracted_path = zf.extract(media_name, path=self.temp_dir)
                if sys.platform == "win32": os.startfile(extracted_path)
                else: subprocess.call(["open" if sys.platform == "darwin" else "xdg-open", extracted_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open media: {e}")

    def display_media_thumbnails(self):
        for widget in self.image_frame.winfo_children(): widget.destroy()
        self.thumbnail_photo_images.clear()
        if not self.chat_file_path: return

        try:
            with zipfile.ZipFile(self.chat_file_path, 'r') as zf:
                # Display image thumbnails
                for img_name in self.image_list:
                    with zf.open(img_name) as image_file:
                        img = Image.open(io.BytesIO(image_file.read()))
                        img.thumbnail((100, 100))
                        photo_img = ImageTk.PhotoImage(img)
                        self.thumbnail_photo_images.append(photo_img)
                        img_label = tk.Label(self.image_frame, image=photo_img, bg=self.colors['dark' if self.dark_mode.get() else 'light']['entry_bg'], cursor="hand2")
                        img_label.pack(side=tk.LEFT, padx=5, pady=5)
                        img_label.bind("<Button-1>", lambda e, name=img_name: self.open_media_external(name))
                # Display video thumbnails
                for vid_name in self.video_list:
                    thumb_img = extract_frame_from_video(self.chat_file_path, vid_name, self.temp_dir, as_thumbnail=True)
                    if thumb_img:
                        photo_img = ImageTk.PhotoImage(thumb_img)
                        self.thumbnail_photo_images.append(photo_img)
                        vid_label = tk.Label(self.image_frame, image=photo_img, bg=self.colors['dark' if self.dark_mode.get() else 'light']['entry_bg'], cursor="hand2")
                        vid_label.pack(side=tk.LEFT, padx=5, pady=5)
                        vid_label.bind("<Button-1>", lambda e, name=vid_name: self.open_media_external(name))

        except Exception as e:
            self.status_var.set(f"Error loading thumbnails: {e}")

    def start_summary_thread(self):
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
                    # Get the most recent 15 images/videos
                    image_filenames_to_send = [msg['image_filename'] for msg in reversed(filtered_messages) if msg['image_filename']][:15]
                    video_filenames_to_send = [msg['video_filename'] for msg in reversed(filtered_messages) if msg['video_filename']][:15]
                
                summary_data = get_summary_from_gemini(api_key, chat_text_for_ai, detail_level, self.chat_file_path, image_filenames_to_send, video_filenames_to_send, self.temp_dir)
                
                if summary_data and 'error' not in summary_data:
                    top_yapper, top_photographer = analyse_chat_participants(filtered_messages)
                    summary_data['top_yapper'] = top_yapper
                    summary_data['top_photographer'] = top_photographer

        except Exception as e:
            self.root.after(0, messagebox.showerror, "Error", f"An unexpected error occurred: {e}")
            summary_data = {"error": "An error occurred during summarisation."}
        finally:
            self.root.after(0, self.display_structured_summary, summary_data)
            self.root.after(0, self.finalize_summary_ui)

    def load_media_for_summary(self, filename):
        """Loads an image or video frame from the zip for inline display."""
        if not self.chat_file_path: return None
        try:
            with zipfile.ZipFile(self.chat_file_path, 'r') as zf:
                if filename in self.image_list:
                    with zf.open(filename) as image_file:
                        img = Image.open(io.BytesIO(image_file.read()))
                        img.thumbnail((500, 500)) # Resize for summary view
                        return ImageTk.PhotoImage(img)
                elif filename in self.video_list:
                    pil_img = extract_frame_from_video(self.chat_file_path, filename, self.temp_dir, as_thumbnail=False)
                    if pil_img:
                        # The function returns a b64 string, need to decode it back to an image
                        img_data = base64.b64decode(pil_img)
                        img = Image.open(io.BytesIO(img_data))
                        img.thumbnail((500, 500)) # Resize for summary view
                        return ImageTk.PhotoImage(img)
        except Exception:
            return None
        return None

    def display_structured_summary(self, data):
        for widget in self.summary_frame.winfo_children(): widget.destroy()
        self.summary_photo_images.clear() # Clear previous summary images
        theme = 'dark' if self.dark_mode.get() else 'light'
        colors = self.colors[theme]

        if not data or 'error' in data:
            error_msg = data.get('error', 'An unknown error occurred.')
            label = tk.Label(self.summary_frame, text=error_msg, wraplength=700, justify="left", bg=colors['summary_bg'], fg='red', font=('Helvetica', 10))
            label.pack(pady=10, padx=10, anchor='w')
            self.status_var.set("An error occurred. Please check the summary window.")
            return

        for part in data.get('summary_parts', []):
            part_type = part.get('type')
            
            if part_type == 'key_message':
                author = part.get('author', 'System')
                content = part.get('content', '')
                key_msg_frame = tk.Frame(self.summary_frame, bg=colors['key_msg_bg'], relief="solid", borderwidth=1)
                key_msg_frame.pack(pady=10, padx=10, fill='x')
                author_label = tk.Label(key_msg_frame, text=f"{author} said:", wraplength=700, justify="left", bg=colors['key_msg_bg'], fg=colors['fg'], font=('Helvetica', 9, 'italic'))
                author_label.pack(pady=(5, 0), padx=10, anchor='w')
                content_label = tk.Label(key_msg_frame, text=content, wraplength=680, justify="left", bg=colors['key_msg_bg'], fg=colors['fg'], font=('Helvetica', 12, 'bold'))
                content_label.pack(pady=(0, 5), padx=10, anchor='w')
            
            elif part_type == 'media':
                filename = part.get('filename')
                if filename:
                    media_photo = self.load_media_for_summary(filename)
                    if media_photo:
                        self.summary_photo_images.append(media_photo)
                        img_label = tk.Label(self.summary_frame, image=media_photo, bg=colors['summary_bg'])
                        img_label.pack(pady=10, padx=10)

            else: # Default to 'text'
                content = part.get('content', '')
                content_label = tk.Label(self.summary_frame, text=content, wraplength=700, justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 10))
                content_label.pack(pady=5, padx=10, anchor='w')

        bullets = data.get('bullet_points', [])
        if bullets:
            tk.Label(self.summary_frame, text="Key Points:", wraplength=700, justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 11, 'bold')).pack(pady=(15, 5), padx=10, anchor='w')
            for point in bullets:
                tk.Label(self.summary_frame, text=f"• {point}", wraplength=680, justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 10)).pack(pady=2, padx=20, anchor='w')
        
        tk.Label(self.summary_frame, text="Chat Analysis:", wraplength=700, justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 11, 'bold')).pack(pady=(15, 5), padx=10, anchor='w')
        table_frame = tk.Frame(self.summary_frame, bg=colors['summary_bg'])
        table_frame.pack(pady=5, padx=20, anchor='w')
        tk.Label(table_frame, text="Top Yapper:", font=('Helvetica', 10, 'bold'), bg=colors['summary_bg'], fg=colors['fg']).grid(row=0, column=0, sticky='w', padx=(0,10))
        tk.Label(table_frame, text=data.get('top_yapper', 'N/A'), font=('Helvetica', 10), bg=colors['summary_bg'], fg=colors['fg']).grid(row=0, column=1, sticky='w')
        tk.Label(table_frame, text="Top Photographer:", font=('Helvetica', 10, 'bold'), bg=colors['summary_bg'], fg=colors['fg']).grid(row=1, column=0, sticky='w', padx=(0,10))
        tk.Label(table_frame, text=data.get('top_photographer', 'N/A'), font=('Helvetica', 10), bg=colors['summary_bg'], fg=colors['fg']).grid(row=1, column=1, sticky='w')
        
        self.status_var.set("Summary generated successfully.")
        
        self.root.update_idletasks()
        controls_height = self.controls_frame.winfo_reqheight()
        button_height = self.summarize_button.winfo_reqheight()
        summary_height = self.summary_frame.winfo_reqheight()
        image_preview_height = self.image_preview_frame.winfo_reqheight()
        status_bar_height = self.status_bar.winfo_reqheight()
        
        total_content_height = controls_height + button_height + summary_height + image_preview_height + status_bar_height + 80
        max_height = self.root.winfo_screenheight()
        new_height = min(max(900, total_content_height), int(max_height * 0.95))
        
        self.root.geometry(f"800x{new_height}")

    def finalize_summary_ui(self):
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.start_cooldown()

    def start_cooldown(self):
        """Starts the cooldown timer on the summarize button."""
        self.summarize_button.config(state=tk.DISABLED)
        self.update_cooldown(self.cooldown_seconds)

    def update_cooldown(self, seconds_left):
        """Updates the button text with the countdown."""
        if seconds_left > 0:
            self.summarize_button.config(text=f"Please wait ({seconds_left}s)")
            self.root.after(1000, self.update_cooldown, seconds_left - 1)
        else:
            self.summarize_button.config(text="Generate Summary", state=tk.NORMAL)


if __name__ == "__main__":
    # To run this code, you need to install:
    # pip install google-generativeai tkinterdnd2 pillow opencv-python
    
    root = TkinterDnD.Tk()
    app = ChatSummarizerApp(root)
    root.mainloop()
