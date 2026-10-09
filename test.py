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
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN", "8815241508:AAHt-iNsD7I6rfnxl54jBceq2uKGM65zw2U")

# ⚠️ СПИСОК USER ID ВСЕХ АДМИНОВ (добавляй сюда айдишники через запятую)
ADMIN_IDS = [7381026134, 8536141131]

MAX_TRACKS_LIMIT = 7
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # Лимит Telegram Bot API (50 MB)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
DB_PATH = "bot_database.db"


class DownloadState(StatesGroup):
    waiting_for_mode_choice = State()
    selecting_tracks = State()


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


def search_youtube_candidates(query: str, limit: int = 5) -> list[dict]:
    """Ищет варианты треков на YouTube и возвращает список словарей с базовой инфой."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'socket_timeout': 15,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'],
            }
        },
    }
    candidates = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            res = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            if res and 'entries' in res:
                for entry in res['entries']:
                    if not entry:
                        continue
                    duration_sec = entry.get('duration')
                    if duration_sec:
                        mins = int(duration_sec // 60)
                        secs = int(duration_sec % 60)
                        dur_str = f"{mins}:{secs:02d}"
                    else:
                        dur_str = "N/A"

                    candidates.append({
                        'id': entry.get('id'),
                        'title': entry.get('title', 'Без названия'),
                        'duration': dur_str
                    })
        except Exception as e:
            print(f"[ОШИБКА ПОИСКА] {query}: {e}")
    return candidates


def download_by_ids_and_zip(video_targets: list[str], user_dir: Path, bot: Bot, chat_id: int, status_msg_id: int, loop: asyncio.AbstractEventLoop) -> Path:
    """Скачивает аудио по прямому списку YouTube ID или поисковым запросам и упаковывает в ZIP."""
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
        for index, target in enumerate(video_targets, start=1):
            status_text = f"⏳ Скачиваю трек {index} из {len(video_targets)}..."

            asyncio.run_coroutine_threadsafe(
                bot.edit_message_text(status_text, chat_id=chat_id, message_id=status_msg_id, parse_mode="Markdown"),
                loop
            )

            try:
                # Если передан ID длинной 11 символов, формируем прямую ссылку
                download_target = f"https://www.youtube.com/watch?v={target}" if len(target) == 11 and not " " in target else f"ytsearch1:{target}"
                ydl.download([download_target])
            except Exception as e:
                print(f"[ОШИБКА] Скачивание '{target}': {e}")

    zip_path = user_dir / "tracks.zip"
    downloaded_files = [f for f in music_dir.iterdir() if f.is_file()]

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for file in downloaded_files:
            zip_file.write(file, arcname=file.name)

    return zip_path


async def execute_download_pipeline(chat_id: int, user_id: int, username: str, targets: list[str], bot: Bot):
    """Единый пайплайн сборки архива и проверки веса перед отправкой."""
    status_msg = await bot.send_message(chat_id, f"Принято! Начинаю обработку {len(targets)} треков...")
    user_dir = Path(f"downloads/user_{user_id}_{status_msg.message_id}")
    loop = asyncio.get_running_loop()

    try:
        zip_path = await asyncio.to_thread(
            download_by_ids_and_zip, targets, user_dir, bot, chat_id, status_msg.message_id, loop
        )

        if not zip_path.exists() or zip_path.stat().st_size <= 22:
            await status_msg.edit_text("Архив получился пустым. Возможно, Ютуб заблокировал запросы.")
            return

        zip_size = zip_path.stat().st_size
        if zip_size > MAX_FILE_SIZE_BYTES:
            size_mb = round(zip_size / (1024 * 1024), 2)
            await status_msg.edit_text(
                f"❌ Итоговый архив весит {size_mb} МБ, что превышает лимит Telegram Bot API (50 МБ).\n"
                "Попробуйте уменьшить количество треков или выбрать менее длительные аудиозаписи."
            )
            return

        await status_msg.edit_text("🤐 Упаковываю в архив и отправляю...")
        document = FSInputFile(zip_path, filename="music_archive.zip")
        await bot.send_document(chat_id, document)

        log_user_and_tracks(user_id, username, len(targets))

    except Exception as err:
        await bot.send_message(chat_id, f"Ошибка при обработке: {err}")
    finally:
        if user_dir.exists():
            shutil.rmtree(user_dir, ignore_errors=True)


@dp.message(CommandStart())
async def start_cmd(message: Message):
    text = (
        "Здорово! Закидывай список треков текстом (каждый с новой строки) "
        f"или присылай .txt файл. Максимум {MAX_TRACKS_LIMIT} треков за раз.\n"
        "Я всё скачаю и пришлю в ZIP-архиве."
    )
    await message.answer(text)


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


async def show_interactive_selection_step(chat_id: int, state: FSMContext, bot: Bot):
    """Показывает вариант выбора для очередного трека из списка."""
    data = await state.get_data()
    raw_tracks = data.get("raw_tracks", [])
    current_index = data.get("current_index", 0)

    if current_index >= len(raw_tracks):
        selected_ids = data.get("selected_ids", [])
        await state.clear()
        await bot.send_message(chat_id, "✅ Все треки успешно выбраны! Начинаю скачивание...")
        await execute_download_pipeline(chat_id, data["user_id"], data["username"], selected_ids, bot)
        return

    track_query = raw_tracks[current_index]
    status_msg = await bot.send_message(chat_id, f"🔍 Ищу варианты для трека `{track_query}`...", parse_mode="Markdown")

    candidates = await asyncio.to_thread(search_youtube_candidates, track_query, 5)

    if not candidates:
        selected_ids = data.get("selected_ids", [])
        selected_ids.append(track_query)
        await state.update_data(selected_ids=selected_ids, current_index=current_index + 1)
        await bot.delete_message(chat_id, status_msg.message_id)
        await show_interactive_selection_step(chat_id, state, bot)
        return

    keyboard_builder = []
    for cand in candidates:
        btn_text = f"{cand['title'][:40]}... ({cand['duration']})" if len(cand['title']) > 40 else f"{cand['title']} ({cand['duration']})"
        keyboard_builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"sel:{cand['id']}")])

    keyboard_builder.append([InlineKeyboardButton(text="⏭ Пропустить трек", callback_data="sel:skip")])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_builder)
    await bot.delete_message(chat_id, status_msg.message_id)
    await bot.send_message(
        chat_id,
        f"🎵 **Трек {current_index + 1} из {len(raw_tracks)}:**\nЗапрос: `{track_query}`\nВыберите подходящий вариант:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def initiate_tracks_flow(message: Message, tracks: list[str], state: FSMContext):
    if not tracks:
        await message.answer("Список треков пустой!")
        return

    if len(tracks) > MAX_TRACKS_LIMIT:
        await message.answer(
            f"❌ Превышен лимит треков! Максимально можно заказать {MAX_TRACKS_LIMIT} треков за один раз.\n"
            "Это ограничение связано с лимитом размера файла Telegram Bot API (50 МБ)."
        )
        return

    await state.set_state(DownloadState.waiting_for_mode_choice)
    await state.update_data(
        raw_tracks=tracks,
        selected_ids=[],
        current_index=0,
        user_id=message.from_user.id,
        username=message.from_user.username
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎯 Выбрать каждый трек вручную", callback_data="mode:manual"),
            InlineKeyboardButton(text="⚡ Скачать автоматически", callback_data="mode:auto")
        ]
    ])

    await message.answer(
        f"Принято {len(tracks)} треков!\nЖелаете выбрать конкретные версии вручную через кнопки или скачать автоматически?",
        reply_markup=kb
    )


@dp.callback_query(DownloadState.waiting_for_mode_choice, F.data.startswith("mode:"))
async def handle_mode_choice(callback: CallbackQuery, state: FSMContext, bot: Bot):
    choice = callback.data.split(":")[1]
    chat_id = callback.message.chat.id
    await bot.delete_message(chat_id, callback.message.message_id)

    data = await state.get_data()

    if choice == "auto":
        raw_tracks = data.get("raw_tracks", [])
        user_id = data.get("user_id")
        username = data.get("username")
        await state.clear()
        await execute_download_pipeline(chat_id, user_id, username, raw_tracks, bot)
    else:
        await state.set_state(DownloadState.selecting_tracks)
        await show_interactive_selection_step(chat_id, state, bot)

    await callback.answer()


@dp.callback_query(DownloadState.selecting_tracks, F.data.startswith("sel:"))
async def handle_track_selection(callback: CallbackQuery, state: FSMContext, bot: Bot):
    target_id = callback.data.split(":")[1]
    chat_id = callback.message.chat.id
    await bot.delete_message(chat_id, callback.message.message_id)

    data = await state.get_data()
    selected_ids = data.get("selected_ids", [])
    current_index = data.get("current_index", 0)

    if target_id != "skip":
        selected_ids.append(target_id)

    await state.update_data(selected_ids=selected_ids, current_index=current_index + 1)
    await callback.answer()

    await show_interactive_selection_step(chat_id, state, bot)


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_tracks(message: Message, state: FSMContext):
    tracks = [line.strip() for line in message.text.split("\n") if line.strip()]
    await initiate_tracks_flow(message, tracks, state)


@dp.message(F.document)
async def handle_file_tracks(message: Message, state: FSMContext, bot: Bot):
    if not message.document.file_name.endswith('.txt'):
        await message.answer("Принимаю только .txt файлы!")
        return

    file_info = await bot.get_file(message.document.file_id)
    file_bytes = await bot.download_file(file_info.file_path)
    content = file_bytes.getvalue().decode('utf-8', errors='ignore')

    tracks = [line.strip() for line in content.split("\n") if line.strip()]
    await initiate_tracks_flow(message, tracks, state)


async def main():
    init_db()

    async with AiohttpSession(timeout=60) as session:
        bot = Bot(token=BOT_TOKEN, session=session)
        await bot.delete_webhook(drop_pending_updates=True)
        print("Бот запущен...")
        await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
