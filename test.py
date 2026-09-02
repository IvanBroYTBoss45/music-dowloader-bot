import os
import shutil
import asyncio
import zipfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
import yt_dlp

# Токен твоего бота из @BotFather
BOT_TOKEN = "8815241508:AAHI_5ZXM6tR9b_gFcOmc9wC0fIrW6fOE1Q"

dp = Dispatcher()


def download_tracks_and_zip(tracks: list[str], user_dir: Path) -> Path:
    """
    Скачивает треки через yt-dlp, перегоняет в MP3 и упаковывает в ZIP.
    Возвращает путь к созданной гига-папке с архивом.
    """
    music_dir = user_dir / "music"
    music_dir.mkdir(parents=True, exist_ok=True)

    # Настройки yt-dlp на базе твоего конфига
    ydl_opts = {
        'format': 'bestaudio/best',

        # Если бот крутится на Linux-сервере, системный ffmpeg цепляется автоматически.
        # Если всё-таки Windows-сервер с фиксированным путем, раскомментируй строку ниже:
        # 'ffmpeg_location': r'D:\ffmpeg\bin',

        'socket_timeout': 15,
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
                # Поиск и скачивание первого совпадения
                ydl.download([f"ytsearch1:{track}"])
            except Exception as e:
                print(f"[ОШИБКА] Не удалось скачать трек '{track}': {e}")

    # Упаковываем все полученные MP3 в один ZIP-архив
    zip_path = user_dir / "tracks.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for file in music_dir.glob("*.mp3"):
            zip_file.write(file, arcname=file.name)

    return zip_path


@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "Салам! Закидывай список треков текстом (каждый с новой строки) "
        "или присылай .txt файл с ними. Я всё скачаю, перегоню в MP3 320 kbps и скину ZIP-архивом."
    )


async def process_tracks_pipeline(message: Message, tracks: list[str]):
    if not tracks:
        await message.answer("Список треков пустой, качать нечего.")
        return

    status_msg = await message.answer(f"Принято! Начинаю обработку {len(tracks)} треков. Жди...")

    user_dir = Path(f"downloads/user_{message.from_user.id}_{message.message_id}")

    try:
        # Запускаем тяжелую загрузку в отдельном потоке, чтобы бот не вешал асинхронный цикл
        zip_path = await asyncio.to_thread(download_tracks_and_zip, tracks, user_dir)

        if not zip_path.exists() or zip_path.stat().st_size == 0:
            await status_msg.edit_text("Не удалось качнуть ни одного трека. Проверь названия.")
            return

        await status_msg.edit_text("Всё скачано и заархивировано! Отправляю ZIP...")

        # Отправляем архив пользователю
        document = FSInputFile(zip_path, filename="music_archive.zip")
        await message.answer_document(document)

    except Exception as err:
        await message.answer(f"Произошёл косяк при обработке: {err}")
    finally:
        # Полный клинап временной папки юзера
        if user_dir.exists():
            shutil.rmtree(user_dir, ignore_errors=True)


@dp.message(F.text)
async def handle_text_tracks(message: Message):
    # Разбиваем сообщение по строкам
    tracks = [line.strip() for line in message.text.split("\n") if line.strip()]
    await process_tracks_pipeline(message, tracks)


@dp.message(F.document)
async def handle_file_tracks(message: Message, bot: Bot):
    # Проверяем, что закинули именно .txt файл
    if not message.document.file_name.endswith('.txt'):
        await message.answer("Принимаются только текстовые файлы (.txt)!")
        return

    # Скачиваем файл во временный буфер
    file_info = await bot.get_file(message.document.file_id)
    file_bytes = await bot.download_file(file_info.file_path)

    content = file_bytes.read().decode('utf-8', errors='ignore')
    tracks = [line.strip() for line in content.split("\n") if line.strip()]

    await process_tracks_pipeline(message, tracks)


async def main():
    bot = Bot(token=BOT_TOKEN)
    print("Бот успешно запущен на сервере...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
