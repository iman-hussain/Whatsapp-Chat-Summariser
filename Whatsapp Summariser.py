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

# --- Core Functions ---

def get_mime_type(filename):
    """Gets the MIME type from a filename extension."""
    # Get the file extension (e.g., '.jpg', '.png') and convert to lowercase
    ext = os.path.splitext(filename)[1].lower()
    # Return the correct MIME type based on the extension
    if ext == '.jpg' or ext == '.jpeg':
        return 'image/jpeg'
    elif ext == '.png':
        return 'image/png'
    elif ext == '.webp':
        return 'image/webp'
    # If the extension is not a supported image type, return None
    return None

def parse_whatsapp_zip(zip_path):
    """
    Parses an exported WhatsApp .zip chat archive.
    It reads the .txt file and identifies messages that correspond to image files.
    """
    # Create an empty list to store the parsed messages
    messages = []
    # Define the file extensions for images we want to process
    image_extensions = ('.jpg', '.jpeg', '.png', '.webp')
    
    # Define a regular expression to match a line in the WhatsApp chat file.
    # It looks for a date, time, author, and message content.
    # Example: 29/01/2020, 23:29 - Author: IMG-20200129-WA0000.jpg (file attached)
    pattern = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4}, \d{2}:\d{2}) - (.*?): (.*?)(?:\s*\(file attached\))?$")

    try:
        # Open the provided zip file in read mode
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # --- FIX: Find the chat file by looking for any .txt file ---
            # Instead of a fixed name, we search for the first file ending with .txt
            chat_filename = None
            for name in zf.namelist(): # Get a list of all files in the zip
                if name.endswith('.txt'): # The chat file is the text file in the archive
                    chat_filename = name
                    break # Stop looking once we've found it
            
            # If a .txt file wasn't found, raise an error
            if not chat_filename:
                raise FileNotFoundError("Could not find a .txt chat file in the zip archive.")

            # Open the chat file from within the zip
            with zf.open(chat_filename) as chat_file:
                # Wrap the file in a TextIOWrapper to handle text encoding properly
                chat_content = io.TextIOWrapper(chat_file, encoding='utf-8')
                
                # Read the chat file line by line
                for line in chat_content:
                    # Try to match our pattern against the current line
                    match = pattern.match(line.strip())
                    if match: # If the line matches our expected format
                        # Extract the different parts (groups) from the match
                        datetime_str, author, message_text = match.groups()
                        
                        image_filename = None # Assume there's no image by default
                        # Check if the message text is a filename for an image
                        if message_text.lower().endswith(image_extensions):
                            # Check if this image file actually exists in the zip archive
                            if message_text in zf.namelist():
                                image_filename = message_text # If it exists, store its name
                        
                        try:
                            # Convert the date/time string into a proper datetime object
                            dt_obj = datetime.strptime(datetime_str, '%d/%m/%Y, %H:%M')
                            # Add the parsed message details to our list of messages
                            messages.append({
                                'timestamp': dt_obj,
                                'author': author.strip(),
                                'message': message_text.strip(),
                                'image_filename': image_filename
                            })
                        except ValueError:
                            # If the date/time can't be parsed, just skip this line
                            continue
    except Exception as e:
        # If any other error occurs while parsing, show an error message
        messagebox.showerror("Parsing Error", f"Failed to parse zip file: {e}")
        return [] # Return an empty list
        
    # Return the final list of parsed messages
    return messages


def filter_messages_by_time(messages, time_range_str):
    """Filters messages based on the selected time range from the dropdown."""
    # If the message list is empty, there's nothing to filter
    if not messages:
        return []

    # Get the current time to calculate start times from
    now = datetime.now()
    # Define the time differences for each dropdown option
    time_deltas = {
        "Last 24 hours": timedelta(days=1),
        "Last 7 days": timedelta(days=7),
        "Last 30 days": timedelta(days=30),
    }

    # If the user selected "All time", return all messages
    if time_range_str == "All time":
        return messages
    
    # If the user selected a specific time range
    if time_range_str in time_deltas:
        # Calculate the start time by subtracting the timedelta from now
        start_time = now - time_deltas[time_range_str]
        # Return a new list containing only messages that are newer than the start time
        return [msg for msg in messages if msg['timestamp'] >= start_time]
    
    # If something unexpected happens, return an empty list
    return []

def format_chat_for_summary(messages):
    """Formats a list of message dictionaries into a single string to send to the AI."""
    # Create an empty list to hold the formatted lines of text
    formatted_lines = []
    # Loop through each message dictionary
    for msg in messages:
        # If the message has an image, use a placeholder text. Otherwise, use the actual message.
        text = "[Image Sent]" if msg['image_filename'] else msg['message']
        # Format the line with timestamp, author, and the message text
        formatted_lines.append(f"[{msg['timestamp'].strftime('%Y-%m-%d %H:%M')}] {msg['author']}: {text}")
    # Join all the formatted lines together with a newline character in between
    return "\n".join(formatted_lines)


def get_summary_from_gemini(api_key, chat_text, zip_path=None, image_filenames=None):
    """
    Uses the Gemini API to summarize the provided chat text and optional images.
    """
    # Check if the API key was provided
    if not api_key:
        raise ValueError("API key is missing.")
    # Check if there is any text to summarize
    if not chat_text:
        return "No messages found in the selected time frame to summarize."

    try:
        # Configure the Gemini library with the user's API key
        genai.configure(api_key=api_key)
        # Initialize the specific Gemini model we want to use (gemini-1.5-flash is good for this)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # --- Prompt Construction ---
        # Start building the prompt we will send to the AI
        prompt_parts = [
            "Please provide a summary of the following WhatsApp group chat conversation. ",
            "The summary should be a concise paragraph of no more than 240 words, followed by key bullet points. ",
        ]
        
        # If there are images to process, add specific instructions for them
        if image_filenames:
            prompt_parts.append("In addition to the text, describe the content and context of the images provided. Integrate the image descriptions into the overall summary. ")
        
        # Add the chat text to the prompt
        prompt_parts.append("\n\n--- CHAT LOG ---\n")
        prompt_parts.append(chat_text)
        prompt_parts.append("\n--- END CHAT LOG ---\n")

        # Add images to the prompt if they exist
        if zip_path and image_filenames:
            prompt_parts.append("\n--- IMAGES ---\n")
            # Open the zip file again to read the image data
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Loop through each image filename we need to send
                for filename in image_filenames:
                    # Get the correct MIME type for the image
                    mime_type = get_mime_type(filename)
                    if mime_type: # Make sure it's a supported image type
                        # Open the image file from within the zip
                        with zf.open(filename) as image_file:
                            # Read the image data as bytes
                            image_bytes = image_file.read()
                            # Encode the image bytes into base64, which is how the API accepts images
                            encoded_image = base64.b64encode(image_bytes).decode('utf-8')
                            # Add the image data to our prompt parts in the required format
                            prompt_parts.append({
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": encoded_image
                                }
                            })
        
        # Send the complete prompt (text and images) to the Gemini model
        response = model.generate_content(prompt_parts)
        # Return the text part of the AI's response
        return response.text
    except Exception as e:
        # Handle potential errors from the API call
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
        # This is the constructor, it sets up the main application window
        self.root = root # The main window
        self.root.title("WhatsApp Chat Summarizer") # Set the window title
        self.root.geometry("800x650") # Set the initial size of the window
        
        # --- Style Configuration ---
        self.style = ttk.Style() # Create a style object to customize widget looks
        self.style.theme_use('clam') # Use a modern-looking theme
        # Configure the appearance of buttons
        self.style.configure("TButton", padding=6, relief="flat", background="#0078D7", foreground="white")
        self.style.map("TButton", background=[('active', '#005A9E')]) # Change color on hover/click
        # Configure frames, labels, entries, progress bar, and checkboxes to have a consistent background
        self.style.configure("TFrame", background="#f0f0f0")
        self.style.configure("TLabel", background="#f0f0f0")
        self.style.configure("TEntry", padding=5)
        self.style.configure("TProgressbar", background="#0078D7", troughcolor="#f0f0f0")
        self.style.configure("TCheckbutton", background="#f0f0f0")

        # --- Main Frame ---
        # Create a main container frame with some padding
        main_frame = ttk.Frame(root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True) # Make it fill the whole window

        # --- Controls Frame ---
        # Create a frame to hold all the user controls (buttons, entry fields, etc.)
        controls_frame = ttk.Frame(main_frame)
        controls_frame.pack(fill=tk.X, pady=(0, 20)) # Pack it at the top
        controls_frame.columnconfigure(1, weight=1) # Make the second column expandable

        # --- File Selection Widgets ---
        # Create a label to show the name of the selected file
        self.file_path_label = ttk.Label(controls_frame, text="No file selected", wraplength=400)
        self.file_path_label.grid(row=0, column=1, sticky="ew", padx=(10, 0)) # Place it in the grid
        # Create the button to open the file dialog
        self.import_button = ttk.Button(controls_frame, text="Import Chat (.zip)", command=self.select_file)
        self.import_button.grid(row=0, column=0, sticky="w") # Place it in the grid

        # --- API Key Widgets ---
        # Create a label for the API key entry field
        ttk.Label(controls_frame, text="Gemini API Key:").grid(row=1, column=0, sticky="w", pady=(10,0))
        # Create the entry field for the user to paste their API key (show '*' for privacy)
        self.api_key_entry = ttk.Entry(controls_frame, show="*")
        self.api_key_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(10,0))

        # --- Time Range Dropdown ---
        ttk.Label(controls_frame, text="Summarize Period:").grid(row=2, column=0, sticky="w", pady=(10,0))
        # Create a string variable to hold the selected option
        self.time_range_var = tk.StringVar(value="All time")
        time_options = ["Last 24 hours", "Last 7 days", "Last 30 days", "All time"]
        # Create the dropdown menu itself
        self.time_range_menu = ttk.OptionMenu(controls_frame, self.time_range_var, time_options[3], *time_options)
        self.time_range_menu.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=(10,0))

        # --- Image Interpretation Checkbox ---
        # Create a boolean variable to track if the checkbox is checked
        self.include_images_var = tk.BooleanVar(value=True)
        # Create the checkbox widget
        self.image_checkbox = ttk.Checkbutton(controls_frame, text="Include Image Summaries (Max 15 images)", variable=self.include_images_var)
        self.image_checkbox.grid(row=3, column=1, sticky="w", padx=(10,0), pady=(10,0))

        # --- Summarize Button ---
        self.summarize_button = ttk.Button(main_frame, text="Generate Summary", command=self.start_summary_thread)
        self.summarize_button.pack(fill=tk.X, pady=10)

        # --- Progress Bar and Summary Display ---
        # Create the progress bar, but don't show it yet
        self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
        # Create the text box where the final summary will be displayed
        self.summary_text = tk.Text(main_frame, wrap=tk.WORD, height=15, state=tk.DISABLED, relief="solid", borderwidth=1, padx=10, pady=10)
        self.summary_text.pack(fill=tk.BOTH, expand=True)
        
        # --- Status Bar ---
        # Create a variable to hold the status text
        self.status_var = tk.StringVar(value="Ready")
        # Create the status bar label at the bottom of the window
        self.status_bar = ttk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=5)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # --- Initialize instance variables ---
        self.chat_file_path = None # To store the path of the imported file
        self.all_messages = [] # To store all parsed messages

    def select_file(self):
        """This function is called when the 'Import Chat' button is clicked."""
        # Open a standard file selection dialog, filtering for .zip files
        path = filedialog.askopenfilename(
            title="Select WhatsApp Chat ZIP File",
            filetypes=(("Zip files", "*.zip"), ("All files", "*.*"))
        )
        # If the user selected a file (didn't cancel)
        if path:
            # Store the file path
            self.chat_file_path = path
            # Update the label to show just the filename
            self.file_path_label.config(text=os.path.basename(path))
            # Update the status bar to show that parsing is in progress
            self.status_var.set("File selected. Parsing messages...")
            self.root.update_idletasks() # Force the GUI to update immediately
            # Call the function to parse the zip file
            self.all_messages = parse_whatsapp_zip(self.chat_file_path)
            # Check if parsing was successful
            if not self.all_messages:
                 messagebox.showwarning("Parsing Issue", "No messages could be parsed. The zip file might be invalid or not contain a recognizable chat file.")
                 self.status_var.set("Parsing failed.")
            else:
                # If successful, update the status bar with the message count
                self.status_var.set(f"Successfully parsed {len(self.all_messages)} messages. Ready to summarize.")

    def start_summary_thread(self):
        """Starts the summarization process in a separate thread to keep the GUI from freezing."""
        # Check if a file has been imported
        if not self.chat_file_path:
            messagebox.showwarning("No File", "Please import a chat zip file first.")
            return
        # Check if an API key has been entered
        if not self.api_key_entry.get():
            messagebox.showwarning("No API Key", "Please enter your Gemini API key.")
            return

        # Disable the summarize button to prevent multiple clicks while it's running
        self.summarize_button.config(state=tk.DISABLED)
        # Update the status bar
        self.status_var.set("Summarizing... This may take a moment.")
        
        # Show and start the indeterminate progress bar
        self.progress_bar.pack(fill=tk.X, pady=(5,10), expand=False)
        self.progress_bar.start(10)
        
        # Create a new thread that will run the 'run_summarization' function
        thread = threading.Thread(target=self.run_summarization)
        thread.daemon = True # Allows the main program to exit even if the thread is running
        thread.start() # Start the thread

    def run_summarization(self):
        """The actual summarization logic that runs in the background thread."""
        summary = "" # Initialize an empty summary string
        try:
            # Get the selected time range from the dropdown
            time_range = self.time_range_var.get()
            # Filter the messages based on the selected time range
            filtered_messages = filter_messages_by_time(self.all_messages, time_range)
            
            # If there are no messages after filtering
            if not filtered_messages:
                summary = "No messages found in the selected time frame."
            else:
                # Format the chat text for the AI
                chat_text_for_ai = format_chat_for_summary(filtered_messages)
                # Get the API key from the entry field
                api_key = self.api_key_entry.get()
                
                image_filenames_to_send = []
                # Check if the user wants to include images
                if self.include_images_var.get():
                    # Get a list of image filenames from the filtered messages
                    # Reverse the list to get the newest images first, and limit it to 15
                    image_filenames_to_send = [
                        msg['image_filename'] for msg in reversed(filtered_messages) 
                        if msg['image_filename']
                    ][:15]

                # Call the Gemini API function with all the necessary data
                summary = get_summary_from_gemini(
                    api_key, 
                    chat_text_for_ai,
                    self.chat_file_path,
                    image_filenames_to_send
                )
        except Exception as e:
            # If any error occurs, schedule an error message to be shown in the main GUI thread
            self.root.after(0, messagebox.showerror, "Error", f"An unexpected error occurred: {e}")
            summary = "An error occurred during summarization."
        finally:
            # No matter what happens, schedule the GUI update functions to run in the main thread
            self.root.after(0, self.update_summary_display, summary)
            self.root.after(0, self.finalize_summary_ui)

    def update_summary_display(self, summary):
        """Updates the text widget with the generated summary. This runs in the main GUI thread."""
        # Enable the text box so we can modify it
        self.summary_text.config(state=tk.NORMAL)
        # Delete any existing text
        self.summary_text.delete(1.0, tk.END)
        # Insert the new summary
        self.summary_text.insert(tk.END, summary)
        # Disable the text box again to make it read-only for the user
        self.summary_text.config(state=tk.DISABLED)
        # Update the status bar based on the result
        if "error" not in summary.lower() and "no messages" not in summary.lower():
            self.status_var.set("Summary generated successfully.")
        else:
            self.status_var.set("An error occurred. Please check the summary window.")

    def finalize_summary_ui(self):
        """Stops the progress bar and re-enables the button. This runs in the main GUI thread."""
        # Stop the progress bar animation
        self.progress_bar.stop()
        # Hide the progress bar from the window
        self.progress_bar.pack_forget()
        # Re-enable the summarize button so the user can run it again
        self.summarize_button.config(state=tk.NORMAL)

# This is the standard entry point for a Python script
if __name__ == "__main__":
    # Make sure the required library is installed. This is just a helpful comment.
    # pip install google-generativeai
    
    # Create the main application window
    root = tk.Tk()
    # Create an instance of our application class
    app = ChatSummarizerApp(root)
    # Start the Tkinter event loop, which waits for user actions (clicks, etc.)
    root.mainloop()
    # When the user closes the window, the program will exit cleanly