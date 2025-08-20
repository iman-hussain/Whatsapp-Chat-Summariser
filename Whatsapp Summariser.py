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

# --- Core Functions ---

def get_mime_type(filename):
    """Gets the MIME type from a filename, required by the Gemini API."""
    ext = os.path.splitext(filename)[1].lower()  # Get the lowercase file extension.
    if ext in ['.jpg', '.jpeg']: return 'image/jpeg'
    elif ext == '.png': return 'image/png'
    elif ext == '.webp': return 'image/webp'
    return None  # Return None for unsupported types.

def parse_whatsapp_zip(zip_path):
    """Extracts messages and media file lists from a WhatsApp .zip export."""
    messages, image_list, video_list = [], [], []
    media_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.mp4')
    # Regex to capture the date, time, author, and message from a line.
    pattern = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4}, \d{2}:\d{2}) - (.*?): (.*?)(?:\s*\(file attached\))?$")

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf: # Open the zip file safely.
            chat_filename = next((name for name in zf.namelist() if name.endswith('.txt')), None)
            if not chat_filename: raise FileNotFoundError("Chat .txt file not found in zip.")
            
            # Get lists of all image and video files within the zip.
            all_media_files = [name for name in zf.namelist() if name.lower().endswith(media_extensions)]
            image_list = [name for name in all_media_files if not name.lower().endswith('.mp4')]
            video_list = [name for name in all_media_files if name.lower().endswith('.mp4')]

            with zf.open(chat_filename) as chat_file: # Open the chat text file from the zip.
                chat_content = io.TextIOWrapper(chat_file, encoding='utf-8') # Read it as UTF-8 text.
                for line in chat_content:
                    match = pattern.match(line.strip())
                    if match:
                        datetime_str, author, message_text = match.groups()
                        image_filename = message_text if message_text in image_list else None
                        video_filename = message_text if message_text in video_list else None
                        try:
                            dt_obj = datetime.strptime(datetime_str, '%d/%m/%Y, %H:%M') # Convert string to datetime object.
                            messages.append({'timestamp': dt_obj, 'author': author.strip(), 'message': message_text.strip(), 'image_filename': image_filename, 'video_filename': video_filename})
                        except ValueError: continue # Skip lines with malformed dates.
    except Exception as e:
        messagebox.showerror("Parsing Error", f"Failed to parse zip file: {e}")
        return [], [], [] # Return empty lists on failure.
        
    return messages, image_list, video_list

def filter_messages_by_time(messages, time_range_str):
    """Filters messages to a specific time range, like 'Last 24 hours'."""
    if not messages: return []
    now = datetime.now()
    time_deltas = {"Last 24 hours": timedelta(days=1), "Last 7 days": timedelta(days=7), "Last 30 days": timedelta(days=30)}
    if time_range_str == "All time": return messages
    if time_range_str in time_deltas:
        start_time = now - time_deltas[time_range_str]
        return [msg for msg in messages if msg['timestamp'] >= start_time] # Return only messages after the start time.
    return []

def format_chat_for_summary(messages):
    """Converts the list of message dictionaries into a single string for the AI."""
    formatted_lines = []
    for msg in messages:
        if msg['image_filename']: text = f"[Image Sent: {msg['image_filename']}]" # Replace media messages with a placeholder.
        elif msg['video_filename']: text = f"[Video Sent: {msg['video_filename']}]"
        else: text = msg['message']
        formatted_lines.append(f"[{msg['timestamp'].strftime('%Y-%m-%d %H:%M')}] {msg['author']}: {text}")
    return "\n".join(formatted_lines) # Join all lines into one string.

def extract_frame_from_video(zip_path, video_filename, temp_dir, as_thumbnail=False):
    """Extracts a single frame from a video (at the 10% mark) using OpenCV."""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            video_path = zf.extract(video_filename, path=temp_dir) # Extract video to a temporary location.
            cap = cv2.VideoCapture(video_path) # Open video file.
            if not cap.isOpened(): return None
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            frame_no = int(total_frames * 0.1) # Target the frame at 10% of the video length.
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no) # Go to the target frame.
            success, frame = cap.read()
            cap.release()
            
            if success:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # Convert color from BGR (OpenCV) to RGB (PIL).
                pil_img = Image.fromarray(frame_rgb) # Convert the frame to a PIL Image.
                
                if as_thumbnail:
                    pil_img.thumbnail((100, 100)) # Resize for thumbnail view.
                    return pil_img

                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG") # Save frame to an in-memory buffer.
                return base64.b64encode(buf.getvalue()).decode('utf-8') # Encode and return as text.
            return None
    except Exception:
        return None # Return None if video processing fails.

def get_summary_from_gemini(api_key, chat_text, detail_level, zip_path=None, image_filenames=None, video_filenames=None, temp_dir=None):
    """Sends the chat data to the Gemini API and gets a structured JSON summary."""
    if not api_key: raise ValueError("API key is missing.")
    if not chat_text: return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Defines the JSON structure the AI must return, ensuring predictable output.
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
                "bullet_points": {"type": "array", "items": {"type": "string"}}
            }
        }
        
        # Maps the UI slider value to specific instructions for the AI's summary detail.
        detail_map = {
            0: {"description": "an extremely brief summary, keeping the total text under 125 words", "quotes": "one single, impactful 'key_message'", "media": "one single 'media' part if media is available"},
            1: {"description": "a standard, medium-detail summary, keeping the total text under 125 words", "quotes": "2-3 'key_message' parts", "media": "2-3 'media' parts if media is available"},
            2: {"description": "an extremely verbose and comprehensive summary, keeping the total text under 500 words", "quotes": "at least 4-5 'key_message' parts", "media": "at least 4-5 'media' parts if media is available"}
        }
        detail_config = detail_map.get(detail_level, detail_map[1]) # Default to medium detail.
        detail_text, quotes_text, media_text = detail_config["description"], detail_config["quotes"], detail_config["media"]
        
        # Assembles the prompt with instructions for the AI.
        prompt_parts = [
            f"Analyse the following WhatsApp chat log. Provide a structured, {detail_text} summary in JSON format. ",
            "The summary should be broken into parts. Most parts should be of type 'text'. ",
            f"Crucially, you must identify {quotes_text}. Ensure these are from a variety of different authors if possible, not just one person. ",
            "For each part, provide the content and the author. For general summary text, the author can be 'narrator'. ",
            "Use the names of the people involved (e.g., 'Simon and Luke discussed...') instead of generic phrases like 'the chat says' or 'the users talked about'. ",
            f"If you discuss a specific image or video, create a 'media' part and set its 'filename' property. You should aim to include {media_text}. Then continue the summary in a new 'text' part.",
            "Finally, provide a list of key 'bullet_points'.\n\n"
        ]
        
        prompt_parts.extend(["--- CHAT LOG ---\n", chat_text, "\n--- END CHAT LOG ---\n"])
        
        if (zip_path and image_filenames) or (zip_path and video_filenames):
             prompt_parts.append("\n--- MEDIA FOR CONTEXT ---\n")

        if zip_path and image_filenames: # Encodes and adds images to the prompt.
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for filename in image_filenames:
                    mime_type = get_mime_type(filename)
                    if mime_type:
                        with zf.open(filename) as image_file:
                            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
                            prompt_parts.append(f"FILENAME: {filename}")
                            prompt_parts.append({"inline_data": {"mime_type": mime_type, "data": encoded_image}})
        
        if zip_path and video_filenames and temp_dir: # Encodes and adds video frames to the prompt.
            for filename in video_filenames:
                encoded_frame = extract_frame_from_video(zip_path, filename, temp_dir)
                if encoded_frame:
                    prompt_parts.append(f"FILENAME: {filename}")
                    prompt_parts.append({"inline_data": {"mime_type": "image/jpeg", "data": encoded_frame}})

        # Sends the prompt to Gemini, configured to return JSON matching the schema.
        response = model.generate_content(prompt_parts, generation_config=genai.types.GenerationConfig(response_mime_type="application/json", response_schema=json_schema))
        return json.loads(response.text) # Parses the JSON text response into a Python dictionary.
    except Exception as e:
        # Provides user-friendly error messages for common API issues.
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
            message_counts[author] = message_counts.get(author, 0) + 1 # Increment text message count.
        if msg['image_filename'] or msg['video_filename']:
            image_counts[author] = image_counts.get(author, 0) + 1 # Increment media message count.
    top_yapper = max(message_counts, key=message_counts.get) if message_counts else "N/A"
    top_photographer = max(image_counts, key=image_counts.get) if image_counts else "N/A"
    return top_yapper, top_photographer


# --- GUI Application ---

class ChatSummarizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WhatsApp Chat Summariser")
        self.root.geometry("950x900")
        
        self.root.drop_target_register(DND_FILES) # Enable file dropping on the window.
        self.root.dnd_bind('<<Drop>>', self.handle_drop) # Link drop event to a handler function.

        self.config = configparser.ConfigParser() # For managing the settings file.
        self.config_file = 'config.ini'
        self.load_config()
        
        self.temp_dir = tempfile.mkdtemp() # Create a temporary directory for extracted files.
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing) # Define cleanup action on window close.

        self.dark_mode = tk.BooleanVar(value=self.detect_system_theme())
        
        self.setup_styles() # Define widget styles.
        self.setup_ui()     # Create and place all widgets.
        self.apply_theme()  # Apply the initial color theme.
        
        self.cooldown_seconds = 10 # Cooldown for the generate button.
        
        # These lists prevent images from being garbage-collected by Python.
        self.thumbnail_photo_images = []
        self.summary_photo_images = []

    # --- NEW METHODS FOR SCROLLING ---
    def _scroll_canvas(self, event, canvas):
        """Generic mousewheel scroll handler for a given canvas widget."""
        # This function handles the actual scrolling action on a canvas.
        # It's designed to be cross-platform, checking for different OS behaviors.
        if sys.platform == "win32":
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif sys.platform == "darwin": # macOS
             canvas.yview_scroll(int(-1 * event.delta), "units")
        else: # Linux
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

    def _on_global_mousewheel(self, event):
        """
        Handles mouse wheel scrolling globally and directs it to the
        canvas widget currently under the mouse pointer.
        """
        # This function determines which widget the mouse is currently over.
        widget_under_cursor = self.root.winfo_containing(event.x_root, event.y_root)
        if widget_under_cursor is None:
            return

        # It then walks up the widget tree from the cursor's position.
        # If it finds one of our scrollable canvases (summary or image),
        # it calls the _scroll_canvas method to scroll that specific canvas.
        current_widget = widget_under_cursor
        while current_widget is not None:
            if current_widget == self.summary_canvas:
                self._scroll_canvas(event, self.summary_canvas)
                return
            if hasattr(self, 'image_canvas') and current_widget == self.image_canvas:
                self._scroll_canvas(event, self.image_canvas)
                return
            
            # Stop searching if we've reached the top-level frame.
            if current_widget == self.main_frame:
                break
                
            current_widget = getattr(current_widget, 'master', None)

    def detect_system_theme(self):
        """Tries to detect the system's dark mode setting on Windows."""
        saved_theme = self.config.getboolean('Settings', 'dark_mode', fallback=None)
        if saved_theme is not None: return saved_theme # Prioritize saved setting.
        try: # Try to read the Windows Registry for the system theme.
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0 # 0 means dark mode.
        except (ImportError, FileNotFoundError): return False # Default to light mode if not Windows or key is missing.

    def setup_styles(self):
        """Defines colors and styles for light and dark modes."""
        self.style = ttk.Style()
        self.style.theme_use('clam') # Use the 'clam' theme for a modern look.
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
        
        # Custom styling for the detail slider.
        self.style.configure("Horizontal.TScale", background=colors['bg'])
        self.style.map('Horizontal.TScale', background=[('active', colors['bg'])], troughcolor=[('!disabled', colors['entry_bg'])])
        self.slider_thumb_img = self.create_slider_thumb(colors['btn_bg'])
        self.style.element_create('custom.Scale.slider', 'image', self.slider_thumb_img, border=8, sticky='nswe')
        self.style.layout('Horizontal.TScale', [('Horizontal.Scale.trough', {'sticky': 'nswe'}), ('custom.Scale.slider', {'side': 'left', 'sticky': ''})])

        self.summary_frame.config(bg=colors['summary_bg'])
        self.image_canvas.config(bg=colors['entry_bg'])
        
        # Recursively apply background colors to non-ttk widgets within the summary frame.
        for child in self.summary_frame.winfo_children():
            if isinstance(child, (tk.Label, tk.Frame)):
                child.config(bg=colors['summary_bg'])
                for grandchild in child.winfo_children():
                     if isinstance(grandchild, tk.Label): grandchild.config(bg=colors['summary_bg'])
        
        for child in self.image_frame.winfo_children():
            if isinstance(child, tk.Label): child.config(bg=colors['entry_bg'])

    def create_slider_thumb(self, color):
        """Creates a circular image to use as the slider's handle."""
        image = Image.new('RGBA', (16, 16), (0,0,0,0)) # Create a transparent image.
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        draw.ellipse((0, 0, 15, 15), fill=color) # Draw a colored circle.
        return ImageTk.PhotoImage(image)

    def toggle_dark_mode(self):
        """Applies the new theme and saves the setting to the config file."""
        self.apply_theme()
        if 'Settings' not in self.config: self.config.add_section('Settings')
        self.config.set('Settings', 'dark_mode', str(self.dark_mode.get()))
        with open(self.config_file, 'w') as configfile: self.config.write(configfile)

    def load_config(self):
        """Loads settings from config.ini, creating it with defaults if it doesn't exist."""
        self.config.read(self.config_file)
        if 'API' not in self.config: self.config['API'] = {'key': ''}
        if 'Settings' not in self.config: self.config['Settings'] = {'remember_key': 'False', 'dark_mode': 'False'}

    def save_api_key(self):
        """Saves the API key and the 'remember' preference to the config file."""
        self.config['API']['key'] = self.api_key_entry.get() if self.remember_api_key_var.get() else ''
        self.config['Settings']['remember_key'] = str(self.remember_api_key_var.get())
        with open(self.config_file, 'w') as configfile: self.config.write(configfile)
    
    def on_closing(self):
        """Cleans up the temporary directory and closes the application."""
        import shutil
        shutil.rmtree(self.temp_dir) # Delete the temp folder and its contents.
        self.root.destroy()

    def setup_ui(self):
        """Creates and lays out all the widgets in the main window."""
        self.main_frame = ttk.Frame(self.root, padding="20")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.controls_frame = ttk.Frame(self.main_frame)
        self.controls_frame.pack(fill=tk.X, pady=(0, 10), expand=False)
        self.controls_frame.columnconfigure(1, weight=1) # Make the entry column expandable.

        self.file_path_label = ttk.Label(self.controls_frame, text="Drop .zip file here or click Import", wraplength=400, anchor="center")
        self.file_path_label.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.import_button = ttk.Button(self.controls_frame, text="Import Chat (.zip)", command=self.select_file)
        self.import_button.grid(row=0, column=0, sticky="w")

        ttk.Label(self.controls_frame, text="Gemini API Key:").grid(row=1, column=0, sticky="w", pady=(10,0))
        self.api_key_entry = ttk.Entry(self.controls_frame, show="*") # Hides the API key text.
        self.api_key_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(10,0))
        self.api_key_entry.insert(0, self.config['API']['key'])
        
        settings_frame = ttk.Frame(self.controls_frame)
        settings_frame.grid(row=2, column=1, sticky='ew', padx=(10,0), pady=(5,0))

        detail_frame = ttk.Frame(settings_frame)
        detail_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(detail_frame, text="Brief").pack(side=tk.LEFT, padx=(0,5))
        self.detail_var = tk.IntVar(value=1) # Variable to store the slider's integer value.
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
        
        content_frame = ttk.Frame(self.main_frame)
        content_frame.pack(fill="both", expand=True, pady=(0, 10))
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=1) 
        content_frame.grid_columnconfigure(1, weight=0)

        # This setup creates a scrollable frame for the summary output.
        self.summary_container = ttk.Frame(content_frame)
        self.summary_container.grid(row=0, column=0, sticky="nsew")
        # MODIFIED: Changed 'summary_canvas' to 'self.summary_canvas' to make it accessible class-wide
        self.summary_canvas = tk.Canvas(self.summary_container, relief="solid", borderwidth=1)
        summary_scrollbar = ttk.Scrollbar(self.summary_container, orient="vertical", command=self.summary_canvas.yview)
        self.summary_frame = tk.Frame(self.summary_canvas)
        summary_scrollbar.pack(side="right", fill="y")
        self.summary_canvas.pack(side="left", fill="both", expand=True)
        self.summary_canvas.create_window((0, 0), window=self.summary_frame, anchor="nw")
        self.summary_canvas.configure(yscrollcommand=summary_scrollbar.set)
        self.summary_frame.bind("<Configure>", lambda e: self.summary_canvas.configure(scrollregion=self.summary_canvas.bbox("all")))

        # This setup creates a VERTICALLY scrollable frame for media thumbnails on the side.
        self.image_preview_frame = ttk.Frame(content_frame)
        self.image_preview_frame.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        self.image_canvas = tk.Canvas(self.image_preview_frame, relief="solid", borderwidth=1, width=120)
        img_scrollbar = ttk.Scrollbar(self.image_preview_frame, orient="vertical", command=self.image_canvas.yview)
        self.image_frame = ttk.Frame(self.image_canvas, style="ImageFrame.TFrame")
        self.image_canvas.create_window((0, 0), window=self.image_frame, anchor="nw")
        self.image_canvas.configure(yscrollcommand=img_scrollbar.set)
        img_scrollbar.pack(side="right", fill="y")
        self.image_canvas.pack(side="left", fill="both", expand=True)
        self.image_frame.bind("<Configure>", lambda e: self.image_canvas.configure(scrollregion=self.image_canvas.bbox("all")))

        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=5)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.chat_file_path, self.all_messages, self.image_list, self.video_list = None, [], [], []
        self.toggle_media_count_menu()

        # MODIFIED: Bind the global mousewheel event to our new handler function.
        # This is done at the end of setup to ensure all widgets have been created.
        self.root.bind_all("<MouseWheel>", self._on_global_mousewheel)
        # For Linux scrolling
        self.root.bind_all("<Button-4>", self._on_global_mousewheel)
        self.root.bind_all("<Button-5>", self._on_global_mousewheel)


    def toggle_media_count_menu(self):
        """Enables/disables the media count dropdown based on settings and file content."""
        total_media = len(self.image_list) + len(self.video_list)
        if self.include_images_var.get() and total_media > 0:
            self.media_count_menu.config(state=tk.NORMAL)
        else:
            self.media_count_menu.config(state=tk.DISABLED)
            
    def update_media_count_menu(self):
        """Populates the media count dropdown with options based on available media."""
        total_media = len(self.image_list) + len(self.video_list)
        menu = self.media_count_menu["menu"]
        menu.delete(0, "end")

        if total_media == 0:
            self.media_count_var.set("0")
            menu.add_command(label="0", command=tk._setit(self.media_count_var, "0"))
        else:
            options = list(range(1, total_media + 1))
            default_val = str(min(15, total_media)) # Default to 15 or total media, whichever is smaller.
            self.media_count_var.set(default_val)
            for option in options:
                menu.add_command(label=str(option), command=tk._setit(self.media_count_var, str(option)))
        
        self.toggle_media_count_menu()

    def handle_drop(self, event):
        """Handles a file being dropped onto the application window."""
        filepath = event.data.strip('{}')
        if filepath.lower().endswith('.zip'): self.process_file(filepath)
        else: messagebox.showwarning("Invalid File", "Please drop a .zip file.")

    def select_file(self):
        """Opens a file dialog to select a chat zip file."""
        path = filedialog.askopenfilename(title="Select WhatsApp Chat ZIP File", filetypes=(("Zip files", "*.zip"),))
        if path: self.process_file(path)

    def process_file(self, path):
        """Parses the selected file and updates the GUI accordingly."""
        self.chat_file_path = path
        self.file_path_label.config(text=os.path.basename(path))
        self.status_var.set("File selected. Parsing messages...")
        self.root.update_idletasks() # Force GUI update to show status change.
        self.all_messages, self.image_list, self.video_list = parse_whatsapp_zip(self.chat_file_path)
        
        if not self.all_messages:
             messagebox.showwarning("Parsing Issue", "No messages could be parsed.")
             self.status_var.set("Parsing failed.")
        else:
            self.status_var.set(f"Successfully parsed {len(self.all_messages)} messages.")
            self.update_media_count_menu()
            self.display_media_thumbnails()

    def open_media_external(self, media_name):
        """Extracts a media file and opens it with the system's default viewer."""
        if not self.chat_file_path: return
        try:
            with zipfile.ZipFile(self.chat_file_path, 'r') as zf:
                extracted_path = zf.extract(media_name, path=self.temp_dir)
                # Use the correct command to open a file based on the OS.
                if sys.platform == "win32": os.startfile(extracted_path)
                else: subprocess.call(["open" if sys.platform == "darwin" else "xdg-open", extracted_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open media: {e}")

    def display_media_thumbnails(self):
        """Creates and shows clickable thumbnails for all media in the chat."""
        for widget in self.image_frame.winfo_children(): widget.destroy()
        self.thumbnail_photo_images.clear()
        if not self.chat_file_path: return

        try:
            with zipfile.ZipFile(self.chat_file_path, 'r') as zf:
                for img_name in self.image_list: # Create thumbnails for images.
                    with zf.open(img_name) as image_file:
                        img = Image.open(io.BytesIO(image_file.read()))
                        img.thumbnail((100, 100))
                        photo_img = ImageTk.PhotoImage(img)
                        self.thumbnail_photo_images.append(photo_img) # Keep a reference.
                        img_label = tk.Label(self.image_frame, image=photo_img, bg=self.colors['dark' if self.dark_mode.get() else 'light']['entry_bg'], cursor="hand2")
                        img_label.pack(side=tk.TOP, padx=5, pady=5)
                        img_label.bind("<Button-1>", lambda e, name=img_name: self.open_media_external(name))
                for vid_name in self.video_list: # Create thumbnails for videos.
                    thumb_img = extract_frame_from_video(self.chat_file_path, vid_name, self.temp_dir, as_thumbnail=True)
                    if thumb_img:
                        photo_img = ImageTk.PhotoImage(thumb_img)
                        self.thumbnail_photo_images.append(photo_img) # Keep a reference.
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
        
        # Run the API call in a separate thread to keep the GUI from freezing.
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
                
                # Get the list of recent media filenames to send to the AI.
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
                
                if summary_data and 'error' not in summary_data: # Add participant stats if successful.
                    top_yapper, top_photographer = analyse_chat_participants(filtered_messages)
                    summary_data['top_yapper'] = top_yapper
                    summary_data['top_photographer'] = top_photographer

        except Exception as e:
            self.root.after(0, messagebox.showerror, "Error", f"An unexpected error occurred: {e}")
            summary_data = {"error": "An error occurred during summarisation."}
        finally:
            # Schedule GUI updates to run on the main thread.
            self.root.after(0, self.display_structured_summary, summary_data)
            self.root.after(0, self.finalize_summary_ui)

    def load_media_for_summary(self, filename):
        """Loads a media file from the zip for inline display in the summary."""
        if not self.chat_file_path: return None
        try:
            with zipfile.ZipFile(self.chat_file_path, 'r') as zf:
                if filename in self.image_list:
                    with zf.open(filename) as image_file:
                        img = Image.open(io.BytesIO(image_file.read()))
                        img.thumbnail((500, 500)) # Resize for display.
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
        """Builds the summary view from the structured JSON data from the AI."""
        for widget in self.summary_frame.winfo_children(): widget.destroy()
        self.summary_photo_images.clear()
        theme = 'dark' if self.dark_mode.get() else 'light'
        colors = self.colors[theme]

        if not data or 'error' in data: # Display any errors returned by the API.
            error_msg = data.get('error', 'An unknown error occurred.')
            label = tk.Label(self.summary_frame, text=error_msg, wraplength=700, justify="left", bg=colors['summary_bg'], fg='red', font=('Helvetica', 10))
            label.pack(pady=10, padx=10, anchor='w')
            self.status_var.set("An error occurred. Please check the summary window.")
            return

        for part in data.get('summary_parts', []): # Create widgets for each part of the summary.
            part_type = part.get('type')
            
            if part_type == 'key_message': # Display key messages in a highlighted frame.
                author, content = part.get('author', 'System'), part.get('content', '')
                key_msg_frame = tk.Frame(self.summary_frame, bg=colors['key_msg_bg'], relief="solid", borderwidth=1)
                key_msg_frame.pack(pady=10, padx=10, fill='x')
                author_label = tk.Label(key_msg_frame, text=f"{author} said:", wraplength=700, justify="left", bg=colors['key_msg_bg'], fg=colors['fg'], font=('Helvetica', 9, 'italic'))
                author_label.pack(pady=(5, 0), padx=10, anchor='w')
                content_label = tk.Label(key_msg_frame, text=content, wraplength=680, justify="left", bg=colors['key_msg_bg'], fg=colors['fg'], font=('Helvetica', 12, 'bold'))
                content_label.pack(pady=(0, 5), padx=10, anchor='w')
            
            elif part_type == 'media': # Display inline images for media parts.
                filename = part.get('filename')
                if filename:
                    media_photo = self.load_media_for_summary(filename)
                    if media_photo:
                        self.summary_photo_images.append(media_photo) # Keep a reference.
                        img_label = tk.Label(self.summary_frame, image=media_photo, bg=colors['summary_bg'])
                        img_label.pack(pady=10, padx=10)

            else: # Display standard text parts.
                content = part.get('content', '')
                content_label = tk.Label(self.summary_frame, text=content, wraplength=700, justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 10))
                content_label.pack(pady=5, padx=10, anchor='w')

        bullets = data.get('bullet_points', []) # Display the final list of bullet points.
        if bullets:
            tk.Label(self.summary_frame, text="Key Points:", wraplength=700, justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 11, 'bold')).pack(pady=(15, 5), padx=10, anchor='w')
            for point in bullets:
                tk.Label(self.summary_frame, text=f"• {point}", wraplength=680, justify="left", bg=colors['summary_bg'], fg=colors['fg'], font=('Helvetica', 10)).pack(pady=2, padx=20, anchor='w')
        
        # Display the chat analysis table.
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
        status_bar_height = self.status_bar.winfo_reqheight()
        
        total_content_height = controls_height + button_height + summary_height + status_bar_height + 80
        max_height = self.root.winfo_screenheight()
        new_height = min(max(900, total_content_height), int(max_height * 0.95))
        
        self.root.geometry(f"950x{new_height}")

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
            self.root.after(1000, self.update_cooldown, seconds_left - 1) # Schedule the next update.
        else:
            self.summarize_button.config(text="Generate Summary", state=tk.NORMAL) # Re-enable the button.


if __name__ == "__main__":
    # To run this code, you need to install:
    # pip install google-generativeai tkinterdnd2 pillow opencv-python
    
    root = TkinterDnD.Tk() # Create the main application window.
    app = ChatSummarizerApp(root) # Instantiate the application class.
    root.mainloop() # Start the GUI event loop.
