import os
import shutil
import asyncio
import zipfile
import subprocess
from pathlib import Path

import static_ffmpeg
# Прописываем путь к ffmpeg в систему автоматически
static_ffmpeg.add_paths()

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.client.session.aiohttp import AiohttpSession
import yt_dlp

BOT_TOKEN = "8815241508:AAHI_5ZXM6tR9b_gFcOmc9wC0fIrW6fOE1Q"

dp = Dispatcher()

def download_tracks_and_zip(tracks: list[str], user_dir: Path) -> Path:
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
        'quiet': False,
        'no_warnings': False,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for track in tracks:
            try:
                print(f"[ИНФО] Скачиваем: {track}")
                ydl.download([f"ytsearch1:{track}"])
            except Exception as e:
                print(f"[ОШИБКА] Ошибка при скачивании '{track}': {e}")

    zip_path = user_dir / "tracks.zip"
    
    # Забираем ВСЕ файлы, которые появились в директории (и mp3, и если вдруг не сконвертировалось)
    downloaded_files = [f for f in music_dir.iterdir() if f.is_file()]
    print(f"[ИНФО] Найдено файлов для упаковки: {len(downloaded_files)}")

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


async def process_tracks_pipeline(message: Message, tracks: list[str]):
    if not tracks:
        await message.answer("Список треков пустой!")
        return

    status_msg = await message.answer(f"Принято! Обрабатываю {len(tracks)} треков...")
    user_dir = Path(f"downloads/user_{message.from_user.id}_{message.message_id}")

    try:
        zip_path = await asyncio.to_thread(download_tracks_and_zip, tracks, user_dir)

        if not zip_path.exists() or zip_path.stat().st_size <= 22:  # 22 байта — размер абсолютно пустого zip
            await status_msg.edit_text("Архив получился пустым. Скорее всего Ютуб заблокировал поиск или трек не найден.")
            return

        await status_msg.edit_text("Готово! Отправляю архив...")
        document = FSInputFile(zip_path, filename="music_archive.zip")
        await message.answer_document(document)

    except Exception as err:
        await message.answer(f"Ошибка при обработке: {err}")
    finally:
        if user_dir.exists():
            shutil.rmtree(user_dir, ignore_errors=True)


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_tracks(message: Message):
    tracks = [line.strip() for line in message.text.split("\n") if line.strip()]
    await process_tracks_pipeline(message, tracks)


@dp.message(F.document)
async def handle_file_tracks(message: Message, bot: Bot):
    if not message.document.file_name.endswith('.txt'):
        await message.answer("Принимаю только .txt файлы!")
        return

    file_info = await bot.get_file(message.document.file_id)
    file_bytes = await bot.download_file(file_info.file_path)
    content = file_bytes.read().decode('utf-8', errors='ignore')
    
    tracks = [line.strip() for line in content.split("\n") if line.strip()]
    await process_tracks_pipeline(message, tracks)


async def main():
    session = AiohttpSession(timeout=60)
    bot = Bot(token=BOT_TOKEN, session=session)
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
