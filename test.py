import os
import shutil
import asyncio
import zipfile
import subprocess
import sqlite3
from pathlib import Path

import static_ffmpeg
# Прописываем путь к ffmpeg в систему автоматически
static_ffmpeg.add_paths()

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.client.session.aiohttp import AiohttpSession
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN", "8815241508:AAHt-iNsD7I6rfnxl54jBceq2uKGM65zw2U")

# ⚠️ СПИСОК USER ID ВСЕХ АДМИНОВ (добавляй сюда айдишники через запятую)
ADMIN_IDS = [7381026134]

dp = Dispatcher()
DB_PATH = "bot_database.db"

# ==================== РАБОТА С БАЗОЙ ДАННЫХ ====================
def init_db():
    """Создает таблицы, если их еще нет"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('total_tracks', 0)")
        conn.commit()

def log_user_and_tracks(user_id: int, username: str, tracks_count: int):
    """Записывает юзера в БД и увеличивает счетчик скачанных треков"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username or ""))
        cursor.execute("UPDATE stats SET value = value + ? WHERE key = 'total_tracks'", (tracks_count,))
        conn.commit()

def get_stats():
    """Возвращает количество юзеров и скачанных треков"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT value FROM stats WHERE key = 'total_tracks'")
        total_tracks = cursor.fetchone()[0]
        return total_users, total_tracks
# ==============================================================


def download_tracks_and_zip(tracks: list[str], user_dir: Path, bot: Bot, chat_id: int, status_msg_id: int, loop: asyncio.AbstractEventLoop) -> Path:
    music_dir = user_dir / "music"
    music_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'socket_timeout': 30,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
        'outtmpl': str(music_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'],
            }
        },
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for index, track in enumerate(tracks, start=1):
            status_text = f"⏳ Скачиваю трек {index} из {len(tracks)}:\n`{track}`"
            
            # Безопасно передаем задачу в основной event loop из потока
            asyncio.run_coroutine_threadsafe(
                bot.edit_message_text(status_text, chat_id=chat_id, message_id=status_msg_id, parse_mode="Markdown"),
                loop
            )

            try:
                ydl.download([f"ytsearch1:{track}"])
            except Exception as e:
                print(f"[ОШИБКА] Ошибка при скачивании '{track}': {e}")

    zip_path = user_dir / "tracks.zip"
    downloaded_files = [f for f in music_dir.iterdir() if f.is_file()]

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for file in downloaded_files:
            zip_file.write(file, arcname=file.name)

    return zip_path


@dp.message(CommandStart())
async def start_cmd(message: Message):
    text = (
        "Здорово! Закидывай список треков текстом (каждый с новой строки) "
        "или присылай .txt файл. Я всё скачаю и пришлю в ZIP-архиве."
    )
    await message.answer(text)


# Хэндлер админки с поддержкой нескольких админов
@dp.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_stats(message: Message):
    users_count, tracks_count = get_stats()
    admin_text = (
        "📊 **Статистика бота:**\n\n"
        f"👥 Всего пользователей в БД: `{users_count}`\n"
        f"🎵 Всего скачано треков: `{tracks_count}`"
    )
    await message.answer(admin_text, parse_mode="Markdown")


@dp.message(Command("check"))
async def check_ffmpeg(message: Message):
    try:
        result = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            first_line = result.stdout.splitlines()[0]
            await message.answer(f"✅ FFmpeg работает:\n`{first_line}`")
        else:
            await message.answer("❌ FFmpeg отвалился с ошибкой.")
    except Exception as e:
        await message.answer(f"❌ FFmpeg не найден: {e}")


async def process_tracks_pipeline(message: Message, tracks: list[str], bot: Bot):
    if not tracks:
        await message.answer("Список треков пустой!")
        return

    status_msg = await message.answer(f"Принято! Начинаю обработку {len(tracks)} треков...")
    user_dir = Path(f"downloads/user_{message.from_user.id}_{message.message_id}")

    # Захватываем текущий event loop в основном асинхронном потоке
    loop = asyncio.get_running_loop()

    try:
        zip_path = await asyncio.to_thread(
            download_tracks_and_zip, tracks, user_dir, bot, message.chat.id, status_msg.message_id, loop
        )

        if not zip_path.exists() or zip_path.stat().st_size <= 22:
            await status_msg.edit_text("Архив получился пустым. Возможно, Ютуб заблокировал запросы.")
            return

        await status_msg.edit_text("🤐 Упаковываю в архив и отправляю...")
        document = FSInputFile(zip_path, filename="music_archive.zip")
        await message.answer_document(document)
        
        # Логируем успешное скачивание в БД
        log_user_and_tracks(message.from_user.id, message.from_user.username, len(tracks))

    except Exception as err:
        await message.answer(f"Ошибка при обработке: {err}")
    finally:
        if user_dir.exists():
            shutil.rmtree(user_dir, ignore_errors=True)


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_tracks(message: Message, bot: Bot):
    tracks = [line.strip() for line in message.text.split("\n") if line.strip()]
    await process_tracks_pipeline(message, tracks, bot)


@dp.message(F.document)
async def handle_file_tracks(message: Message, bot: Bot):
    if not message.document.file_name.endswith('.txt'):
        await message.answer("Принимаю только .txt файлы!")
        return

    file_info = await bot.get_file(message.document.file_id)
    file_bytes = await bot.download_file(file_info.file_path)
    content = file_bytes.getvalue().decode('utf-8', errors='ignore')
    
    tracks = [line.strip() for line in content.split("\n") if line.strip()]
    await process_tracks_pipeline(message, tracks, bot)


async def main():
    init_db()
    
    async with AiohttpSession(timeout=60) as session:
        bot = Bot(token=BOT_TOKEN, session=session)
        await bot.delete_webhook(drop_pending_updates=True)
        print("Бот запущен...")
        await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
