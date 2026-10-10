# 🎧 YouTube Tracks Downloader Bot

A Telegram bot built with **aiogram 3.x** that takes a list of tracks (as text or a `.txt` file), searches YouTube for each one, and sends the downloaded MP3s back as a ZIP archive.

Features both **manual selection** (choose the right version from 5 candidates) and **auto mode** (downloads the top result instantly).

## ✨ Features

- 📝 Accepts tracks as plain text (one per line) or as a `.txt` file
- 🎯 **Manual mode** — shows 5 YouTube candidates with titles and durations, lets the user pick
- ⚡ **Auto mode** — skips selection and grabs the first result for each track
- 📦 Sends all tracks as a single ZIP archive
- 🗃️ SQLite database tracks users and total downloaded tracks
- 📊 Admin-only `/admin` command with bot statistics
- 🩺 `/check` command to verify FFmpeg is working
- 🧹 Auto-cleans temporary files after sending
- 📏 Enforces a 50 MB Telegram file size limit and a 7-track-per-request cap

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| Telegram Bot API | `aiogram 3.x` |
| FSM | `aiogram.fsm` (MemoryStorage) |
| Downloading | `yt-dlp` |
| Conversion | `static-ffmpeg` + `ffmpeg` |
| Database | `sqlite3` |
| Async | `asyncio` |

## 📦 Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your_user/tracks-downloader-bot.git
   cd tracks-downloader-bot

2. Install dependencies:
pip install aiogram yt-dlp static-ffmpeg
3. Set your bot token (and admin IDs):
BOT_TOKEN = "YOUR_BOT_TOKEN"
ADMIN_IDS = [123456789, 987654321]
4. Run:
python bot.py
 
🚀 Usage
1. Send /start to the bot
2. Send a list of tracks (one per line) or upload a .txt file
3. Choose the mode:
	• 🎯 Manual — pick the exact version for each track from 5 YouTube candidates
	• ⚡ Auto — download the first result for each track
4. Wait for the bot to build and send the ZIP archive 
📋 Commands
Command Access Description
/start Everyone Shows usage instructions
/check Everyone Verifies FFmpeg is available
/admin Admins only Shows total users and total downloaded tracks

 
📁 Project Structure
.
├── bot.py               # main file
├── bot_database.db      # SQLite database (created automatically)
├── downloads/           # temporary files (cleaned after sending)
└── README.md
 
⚙️ How It Works
1. User sends a list of tracks or a .txt file
2. Bot asks for the download mode (manual / auto)
3. For each track:
	• Manual: searches YouTube, shows 5 candidates with duration, user picks one
	• Auto: downloads the first result immediately
4. yt-dlp downloads audio and converts it to MP3 (320 kbps) via ffmpeg
5. All tracks are packed into a ZIP and sent as a Telegram document
6. Temporary files are deleted, stats are updated in SQLite 
🔧 Configuration
• Max tracks per request — MAX_TRACKS_LIMIT = 7
• Max file size — MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
• Audio quality — preferredquality: '320' in ydl_opts
• Search results shown — search_youtube_candidates(..., limit=5)
• Admin IDs — edit the ADMIN_IDS list 
📝 Notes
• static-ffmpeg bundles ffmpeg, no system install required
• Bot uses player_client: ['android', 'ios'] to bypass YouTube restrictions
• Database stores users and total track count; delete bot_database.db to reset
• The 50 MB limit comes from Telegram Bot API — bigger archives are rejected before sending 
📄 License
 
MIT — do whatever you want.