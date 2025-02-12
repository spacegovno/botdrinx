import os
import logging
import sqlite3
from logging.handlers import RotatingFileHandler
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, FSInputFile
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv  # Импортируем load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

# Настройка логирования
handler = RotatingFileHandler(
    "bot.log",
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[handler, logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")  # Получаем строку из .env
ADMIN_IDS = set(map(int, ADMIN_IDS.split(","))) if ADMIN_IDS else set()
DATABASE_NAME = os.getenv("DATABASE_NAME", "bot_database.db")

# Проверка токена
if not BOT_TOKEN:
    logger.error("Токен бота не найден в .env!")
    exit(1)

# Инициализация бота
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


class Database:
    def __init__(self, db_name):
        self.conn = sqlite3.connect(db_name)
        self.create_table()

    def create_table(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT NULL,
                    first_name TEXT DEFAULT '',
                    last_name TEXT DEFAULT NULL,
                    language_code TEXT DEFAULT 'ru',
                    is_bot INTEGER DEFAULT 0,
                    date_joined TIMESTAMP
                )""")

    def add_user(self, user: types.User):
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT INTO users (
                        user_id, username, first_name, last_name,
                        language_code, is_bot, date_joined
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user.id,
                    user.username or None,
                    user.first_name or '',
                    user.last_name or None,
                    user.language_code or 'ru',
                    1 if user.is_bot else 0,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
            logger.info(f"User {user.id} added")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"User {user.id} exists")
            return False
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False

    def remove_user(self, user_id):
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM users WHERE user_id = ?",
                (user_id,))
            if cursor.rowcount > 0:
                logger.info(f"User {user_id} removed")
                return True
            logger.warning(f"User {user_id} not found")
            return False

    def get_all_users(self):
        with self.conn:
            return self.conn.execute(
                "SELECT * FROM users").fetchall()

    def close(self):
        self.conn.close()


db = Database(DATABASE_NAME)


class BroadcastState(StatesGroup):
    waiting_for_content = State()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    try:
        if db.add_user(message.from_user):
            if message.from_user.id in ADMIN_IDS:
                text = "👋 Привет, администратор!\nКоманды: /help"
            else:
                text = "📨 Привет! Отписаться: /unsubscribe"
            await message.answer(text)
        else:
            await message.answer("Вы уже подписаны!")
    except Exception as e:
        logger.error(f"/start error: {e}")
        await message.answer("Ошибка, попробуйте позже")


@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    if db.remove_user(message.from_user.id):
        await message.answer("❌ Отписались")
    else:
        await message.answer("Вы не подписаны")


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Доступ запрещен")
        return
    await message.answer("📤 Отправьте сообщение для рассылки...")
    await state.set_state(BroadcastState.waiting_for_content)


@dp.message(BroadcastState.waiting_for_content, F.document | F.text)
async def process_broadcast(message: Message, state: FSMContext):
    users = db.get_all_users()
    success, errors = 0, 0

    for user in users:
        try:
            if message.document and message.document.mime_type == "application/pdf":
                await bot.send_document(
                    chat_id=user[0],
                    document=message.document.file_id,
                    caption=message.caption)
            else:
                await bot.send_message(
                    chat_id=user[0],
                    text=message.html_text)
            success += 1
        except Exception as e:
            errors += 1
            logger.error(f"Error to {user[0]}: {e}")

    await message.answer(
        f"✅ Рассылка завершена\nУспешно: {success}\nОшибок: {errors}")
    await state.clear()


@dp.message(Command("read_db"))
async def cmd_read_db(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    data = db.get_all_users()
    response = "📋 База данных:\n" + "\n".join(
        f"ID: {row[0]}, Имя: {row[2]}" for row in data)
    await message.answer(response[:4000])  # Ограничение Telegram


@dp.message(Command("export_db"))
async def cmd_export_db(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    data = db.get_all_users()
    with open("export.txt", "w") as f:
        f.write("\n".join(str(row) for row in data))
    await message.answer_document(FSInputFile("export.txt"))


@dp.message(Command("help"))
async def cmd_help(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    text = """🔧 Команды админа:
/broadcast - Рассылка
/read_db - Просмотр БД
/export_db - Экспорт БД
/cancel - Отмена"""
    await message.answer(text)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
    db.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())