# WhatsApp Chat Summariser

> [!WARNING]
>
> Privacy Disclaimer: For Educational Use Only
>
> This application sends your chat content to Google's servers for processing via the Gemini API. Do not use this tool with sensitive or private conversations. By using this application, you acknowledge that you have the consent of all chat participants to share the conversation data with a third-party service. Please read the full Privacy, Security, and Data Handling section before proceeding.

A desktop application that uses the Google Gemini API to analyse and create structured, detailed summaries of your exported WhatsApp chat logs, complete with media integration.

## Table of Contents

* [Features](https://www.google.com/search?q=%23features "null")
* [Setup and Installation](https://www.google.com/search?q=%23setup-and-installation "null")
  * [Step 1: Install Python](https://www.google.com/search?q=%23step-1-install-python "null")
  * [Step 2: Get Your Gemini API Key](https://www.google.com/search?q=%23step-2-get-your-gemini-api-key "null")
  * [Step 3: Download the Summariser](https://www.google.com/search?q=%23step-3-download-the-summariser "null")
  * [Step 4: Install Dependencies](https://www.google.com/search?q=%23step-4-install-dependencies "null")
* [How to Use](https://www.google.com/search?q=%23how-to-use "null")
  * [Step 1: Export Your WhatsApp Chat](https://www.google.com/search?q=%23step-1-export-your-whatsapp-chat "null")
  * [Step 2: Run the Application](https://www.google.com/search?q=%23step-2-run-the-application "null")
* [Using the App Interface](https://www.google.com/search?q=%23using-the-app-interface "null")
* [Privacy, Security, and Data Handling](https://www.google.com/search?q=%23privacy-security-and-data-handling "null")

## Features

* **AI-Powered Summaries** : Leverages Google's Gemini 1.5 Flash to understand conversations and generate insightful summaries.
* **Adjustable Detail** : Use a simple slider to choose between a brief, single-sentence summary or a highly detailed, verbose breakdown.
* **Media Analysis** : The AI can "see" the images and videos in your chat to provide richer, more contextual summaries.
* **Structured Output** : Summaries are cleanly formatted with highlighted key messages, bullet points, and an analysis of the most active participants.
* **Flexible Time Ranges** : Analyse the entire chat history or focus on the last 24 hours, 7 days, or 30 days.
* **Customisable Media Inclusion** : Choose exactly how many of the most recent media files you want the AI to analyse.
* **Modern UI** : Features a clean, easy-to-use interface with drag-and-drop support and a dark mode option.

## Setup and Installation

### Step 1: Install Python

If you don't already have Python on your system, follow the instructions for your operating system.

On Windows:

The recommended way to install Python on Windows is from the Microsoft Store. This ensures it's correctly added to your system's PATH.

1. Open the Microsoft Store.
2. Search for "Python" (e.g., Python 3.11 or the latest version).
3. Click `Install`.

On macOS / Linux:

Download the latest version from the official Python website.

1. Go to [python.org/downloads](https://www.python.org/downloads/ "null").
2. Download the installer for your operating system.
3. Run the installer, ensuring you follow the on-screen instructions. On macOS, make sure to run the `Install Certificates.command` file that comes with the installation.

### Step 2: Get Your Gemini API Key

This application requires a Google Gemini API key to function. You can get one for free from Google AI Studio.

**Watch the video below for a step-by-step guide:**

**Written Instructions:**

1. Visit [Google AI Studio](https://aistudio.google.com/ "null").
2. Sign in with your Google account.
3. Click on **"Get API key"** and then  **"Create API key in new project"** .
4. Copy the generated key. You will need to paste this into the application later.

### Step 3: Download the Summariser

Download the `Whatsapp Summariser.py` file from this repository and place it in a dedicated folder on your computer.

### Step 4: Install Dependencies

Open a terminal (on macOS/Linux) or Command Prompt (on Windows), navigate to the folder where you saved the script, and run the following command to install the necessary Python libraries:

```
pip install google-generativeai tkinterdnd2 pillow opencv-python

```

## How to Use

### Step 1: Export Your WhatsApp Chat

You need to export the chat you want to analyse from your phone. **It is essential that you select "Attach Media" / "Include Media"** for the full functionality.

**On iOS (iPhone):**

1. Open the WhatsApp chat.
2. Tap the contact or group name at the top.
3. Scroll down and tap `Export Chat`.
4. Choose `Attach Media`.
5. Save or send the resulting `.zip` file to your computer (e.g., via AirDrop, email, or saving to Files).

**On Android:**

1. Open the WhatsApp chat.
2. Tap the three-dot menu icon in the top-right corner.
3. Tap `More` > `Export chat`.
4. Choose `Include Media`.
5. Save or send the resulting `.zip` file to your computer.

### Step 2: Run the Application

Once the dependencies are installed, you can run the script. In your terminal or command prompt, make sure you are in the correct folder and run:

```
python "Whatsapp Summariser.py"

```

*(Note: You may need to use `python3` instead of `python` on some systems).*

## Using the App Interface

1. **Paste your Gemini API Key** into the designated field. You can check "Remember API Key" to save it for future use.
2. **Drag and drop** your exported WhatsApp `.zip` file onto the application window, or click the "Import Chat (.zip)" button to select it manually.
3. **Adjust the settings** to your preference:
   * **Brief/Verbose Slider** : Control the level of detail in the summary.
   * **Summarise Period** : Choose the timeframe you want to analyse.
   * **Include Media** : Check this box to allow the AI to analyse images and videos.
   * **Recent Media** : Select how many of the most recent media files to include in the analysis.
4. Click **"Generate Summary"** and wait for the result!

## Privacy, Security, and Data Handling

> [!IMPORTANT]
>
> This section details how your data is handled. Please read it carefully.

### Data Flow

1. **Local Processing** : The application first unzips and parses your WhatsApp chat file (`.txt` and media) entirely on your local machine. It does **not** upload the entire zip file.
2. **API Transmission** : When you click "Generate Summary", the following data is sent to the Google Gemini API over a secure (HTTPS) connection:

* The text content of your chat for the selected period.
* The selected number of recent images and video frames, which are encoded into text (base64) before being sent.

1. **No Data is Stored by This Application** : The script does not save your chat content, images, or summaries anywhere. The only piece of information it can save (if you check the box) is your API key, which is stored in a `config.ini` file in the same folder as the script.

### Risks and Considerations

* **Third-Party Processing** : Your chat data is processed by Google. While Google has its own privacy policies, you are still sending potentially personal information to a third-party service. According to Google's terms, they may use API content to improve their services.
* **Consent is Required** : You are responsible for ensuring you have the explicit consent of **every participant** in the chat before using this tool. Sharing a private conversation without permission may violate privacy.
* **Educational Purpose** : This tool is provided for educational and demonstration purposes only. It is a practical example of how to interact with a powerful AI model. It is **not** intended for use with confidential, sensitive, or professional conversations.

By using this software, you agree that you understand these risks and have obtained the necessary permissions from all chat participants. The author of this tool assumes no liability for any misuse of this software or any data privacy violations that may occur.
