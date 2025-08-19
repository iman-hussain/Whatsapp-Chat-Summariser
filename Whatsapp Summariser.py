import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import re
from datetime import datetime, timedelta
import google.generativeai as genai
import threading

# --- Core Functions ---

def parse_whatsapp_chat(file_path):
    """
    Parses an exported WhatsApp .txt chat file.
    Handles different date formats and message types (user vs. system) by trying multiple patterns.
    It also filters out "<Media omitted>" messages which are not useful for summarization.
    """
    # List of regex patterns and their corresponding datetime formats.
    # The regex captures (datetime_string, author, message)
    patterns = [
        # Format: 29/01/2020, 23:29 - Author: Message (Handles 4-digit year, common in many regions)
        (re.compile(r"^(\d{1,2}/\d{1,2}/\d{4}, \d{2}:\d{2}) - (?:(.*?): )?(.*)"), '%d/%m/%Y, %H:%M'),
        # Format: [29/01/2024, 23:30:00] Author: Message
        (re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{4}, \d{2}:\d{2}:\d{2})\] (?:(.*?): )?(.*)"), '%d/%m/%Y, %H:%M:%S'),
        # Format: 1/29/24, 11:30 PM - Author: Message (US format with 2-digit year)
        (re.compile(r"^(\d{1,2}/\d{1,2}/\d{2}, \d{1,2}:\d{2} [AP]M) - (?:(.*?): )?(.*)"), '%m/%d/%y, %I:%M %p'),
        # Format: 29/01/24, 23:30 - Author: Message (EU format with 2-digit year)
        (re.compile(r"^(\d{1,2}/\d{1,2}/\d{2}, \d{2}:\d{2}) - (?:(.*?): )?(.*)"), '%d/%m/%y, %H:%M'),
    ]

    messages = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            for pattern, date_format in patterns:
                match = pattern.match(line)
                if match:
                    datetime_str, author, message_text = match.groups()
                    
                    # If author is None, it's a system message (e.g., "You added...")
                    if author is None:
                        author = "System"
                    
                    # Ignore media omitted messages as they don't add to the summary context
                    if message_text.strip() == "<Media omitted>":
                        continue

                    try:
                        dt_obj = datetime.strptime(datetime_str, date_format)
                        messages.append({
                            'timestamp': dt_obj,
                            'author': author.strip(),
                            'message': message_text.strip()
                        })
                        # Break from inner loop once a pattern matches
                        break
                    except ValueError:
                        # This format matched the regex but not the datetime parser,
                        # which is unlikely but we continue to be safe.
                        continue
    return messages

def filter_messages_by_time(messages, time_range_str):
    """Filters messages based on the selected time range."""
    if not messages:
        return []

    now = datetime.now()
    time_deltas = {
        "Last 24 hours": timedelta(days=1),
        "Last 7 days": timedelta(days=7),
        "Last 30 days": timedelta(days=30),
    }

    if time_range_str == "All time":
        return messages
    
    if time_range_str in time_deltas:
        start_time = now - time_deltas[time_range_str]
        return [msg for msg in messages if msg['timestamp'] >= start_time]
    
    return []

def format_chat_for_summary(messages):
    """Formats a list of message dictionaries into a single string for the AI."""
    return "\n".join(
        f"[{msg['timestamp'].strftime('%Y-%m-%d %H:%M')}] {msg['author']}: {msg['message']}"
        for msg in messages
    )

def get_summary_from_gemini(api_key, chat_text):
    """
    Uses the Gemini API to summarize the provided chat text.
    """
    if not api_key:
        raise ValueError("API key is missing.")
    if not chat_text:
        return "No messages found in the selected time frame to summarize."

    try:
        genai.configure(api_key=api_key)
        # *** FIX: Updated model name from 'gemini-pro' to 'gemini-1.5-flash' ***
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = (
            "Please summarize the following WhatsApp group chat conversation. "
            "Ignore system messages that don't contribute to the conversation's context (e.g., 'User was added'). "
            "The summary should be a concise paragraph of no more than 240 words. "
            "After the paragraph, provide a few key bullet points highlighting the main topics, decisions, or action items. "
            "Do not start with 'The user wants a summary...'. Directly provide the summary.\n\n"
            "Here is the chat:\n---\n"
            f"{chat_text}\n---\n"
        )
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        # Provide a more user-friendly error message for common API issues
        error_str = str(e)
        if "API key not valid" in error_str:
            return "An error occurred with the Gemini API: The API key is not valid. Please check your key and try again."
        elif "is not found for API version" in error_str:
             return f"An error occurred with the Gemini API: The model name is incorrect or not supported. ({e})"
        else:
            return f"An error occurred with the Gemini API: {e}"

# --- GUI Application ---

class ChatSummarizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WhatsApp Chat Summarizer")
        self.root.geometry("800x600")
        
        # Style configuration
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure("TButton", padding=6, relief="flat", background="#0078D7", foreground="white")
        self.style.map("TButton", background=[('active', '#005A9E')])
        self.style.configure("TFrame", background="#f0f0f0")
        self.style.configure("TLabel", background="#f0f0f0")
        self.style.configure("TEntry", padding=5)
        self.style.configure("TProgressbar", background="#0078D7", troughcolor="#f0f0f0")

        # Main frame
        main_frame = ttk.Frame(root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Top Controls ---
        controls_frame = ttk.Frame(main_frame)
        controls_frame.pack(fill=tk.X, pady=(0, 20))
        controls_frame.columnconfigure(1, weight=1)

        # File selection
        self.file_path_label = ttk.Label(controls_frame, text="No file selected", wraplength=400)
        self.file_path_label.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        
        self.import_button = ttk.Button(controls_frame, text="Import Chat (.txt)", command=self.select_file)
        self.import_button.grid(row=0, column=0, sticky="w")

        # API Key
        ttk.Label(controls_frame, text="Gemini API Key:").grid(row=1, column=0, sticky="w", pady=(10,0))
        self.api_key_entry = ttk.Entry(controls_frame, show="*")
        self.api_key_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(10,0))

        # Time range dropdown
        ttk.Label(controls_frame, text="Summarize Period:").grid(row=2, column=0, sticky="w", pady=(10,0))
        self.time_range_var = tk.StringVar(value="All time")
        time_options = ["Last 24 hours", "Last 7 days", "Last 30 days", "All time"]
        self.time_range_menu = ttk.OptionMenu(controls_frame, self.time_range_var, time_options[3], *time_options)
        self.time_range_menu.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=(10,0))

        # Summarize button
        self.summarize_button = ttk.Button(main_frame, text="Generate Summary", command=self.start_summary_thread)
        self.summarize_button.pack(fill=tk.X, pady=10)

        # --- Summary Display ---
        self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
        # This will be packed/unpacked as needed

        self.summary_text = tk.Text(main_frame, wrap=tk.WORD, height=15, state=tk.DISABLED, relief="solid", borderwidth=1, padx=10, pady=10)
        self.summary_text.pack(fill=tk.BOTH, expand=True)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=5)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.chat_file_path = None
        self.all_messages = []

    def select_file(self):
        """Opens a file dialog to select a chat file."""
        path = filedialog.askopenfilename(
            title="Select WhatsApp Chat File",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*"))
        )
        if path:
            self.chat_file_path = path
            self.file_path_label.config(text=path.split('/')[-1])
            self.status_var.set("File selected. Parsing messages...")
            self.root.update_idletasks() # Force GUI update
            try:
                self.all_messages = parse_whatsapp_chat(self.chat_file_path)
                if not self.all_messages:
                     messagebox.showwarning("Parsing Issue", "No messages could be parsed. The file might be empty, in an unsupported format, or only contain media.")
                     self.status_var.set("Parsing failed or no valid messages found.")
                else:
                    self.status_var.set(f"Successfully parsed {len(self.all_messages)} messages. Ready to summarize.")
            except Exception as e:
                messagebox.showerror("Parsing Error", f"Failed to parse the chat file:\n{e}")
                self.status_var.set("Error parsing file.")

    def start_summary_thread(self):
        """Starts the summarization process in a separate thread to keep the GUI responsive."""
        if not self.chat_file_path:
            messagebox.showwarning("No File", "Please import a chat file first.")
            return
        if not self.api_key_entry.get():
            messagebox.showwarning("No API Key", "Please enter your Gemini API key.")
            return

        self.summarize_button.config(state=tk.DISABLED)
        self.status_var.set("Summarizing... This may take a moment.")
        
        # Show and start the progress bar
        self.progress_bar.pack(fill=tk.X, pady=(5,10), expand=False)
        self.progress_bar.start(10)
        
        thread = threading.Thread(target=self.run_summarization)
        thread.daemon = True
        thread.start()

    def run_summarization(self):
        """The actual summarization logic that runs in the background."""
        summary = ""
        try:
            time_range = self.time_range_var.get()
            filtered_messages = filter_messages_by_time(self.all_messages, time_range)
            
            if not filtered_messages:
                summary = "No messages found in the selected time frame."
            else:
                chat_text_for_ai = format_chat_for_summary(filtered_messages)
                api_key = self.api_key_entry.get()
                summary = get_summary_from_gemini(api_key, chat_text_for_ai)
        except Exception as e:
            self.root.after(0, messagebox.showerror, "Error", f"An unexpected error occurred: {e}")
            summary = "An error occurred during summarization."
        finally:
            # Schedule GUI updates from the main thread
            self.root.after(0, self.update_summary_display, summary)
            self.root.after(0, self.finalize_summary_ui)

    def update_summary_display(self, summary):
        """Updates the text widget with the summary."""
        self.summary_text.config(state=tk.NORMAL)
        self.summary_text.delete(1.0, tk.END)
        self.summary_text.insert(tk.END, summary)
        self.summary_text.config(state=tk.DISABLED)
        if "error" not in summary.lower() and "no messages" not in summary.lower():
            self.status_var.set("Summary generated successfully.")
        else:
            self.status_var.set("An error occurred. Please check the summary window.")


    def finalize_summary_ui(self):
        """Stops the progress bar and re-enables the button."""
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.summarize_button.config(state=tk.NORMAL)

if __name__ == "__main__":
    # To run this code, you need to install the google-generativeai library:
    # pip install google-generativeai
    
    root = tk.Tk()
    app = ChatSummarizerApp(root)
    root.mainloop()
