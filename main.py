import os
import logging
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, FSInputFile
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = set(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else set()

# Инициализация бота
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


# Класс для работы с базой данных
class Database:
    def __init__(self):
        self.conn = sqlite3.connect("bot_database.db")
        self.create_table()

    def create_table(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT,
                    is_bot INTEGER,
                    date_joined TIMESTAMP
                )
            """)

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
                    user.username,
                    user.first_name,
                    user.last_name,
                    user.language_code,
                    user.is_bot,
                    datetime.now()
                ))
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_user(self, user_id):
        with self.conn:
            cursor = self.conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            return cursor.rowcount > 0

    def get_all_users(self):
        with self.conn:
            cursor = self.conn.execute("SELECT * FROM users")
            return cursor.fetchall()

    def get_new_users(self, days):
        with self.conn:
            cursor = self.conn.execute("""
                SELECT COUNT(*) FROM users WHERE date_joined >= ?
            """, (datetime.now() - timedelta(days=days),))
            return cursor.fetchone()[0]

    def export_to_csv(self):
        users = self.get_all_users()
        df = pd.DataFrame(users, columns=[
            "user_id", "username", "first_name",
            "last_name", "language_code", "is_bot", "date_joined"
        ])
        df.to_csv("database_export.csv", index=False)
        return "database_export.csv"

    def close(self):
        self.conn.close()


# Инициализация базы данных
db = Database()


class BroadcastState(StatesGroup):
    waiting_for_content = State()
    waiting_for_confirmation = State()


# Команда помощи
@dp.message(Command("help"))
async def cmd_help(message: Message):
    commands = get_available_commands(message.from_user.id in ADMIN_IDS)
    await message.answer(f"📜 Доступные команды:\n{commands}")


def get_available_commands(is_admin: bool) -> str:
    user_commands = """
👤 Команды для пользователей:
/start - Подписаться на рассылку
/unsubscribe - Отписаться от рассылки
/help - Показать это сообщение
    """

    admin_commands = """
🛠 Админ-команды:
/stats - Статистика пользователей
/broadcast - Сделать рассылку
/viewdb - Просмотр базы данных
/exportdb - Экспорт базы данных
    """ if is_admin else ""

    return user_commands + admin_commands


# Команда старта
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


# Команда отписки
@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    if db.remove_user(message.from_user.id):
        await message.answer("❌ Отписались")
    else:
        await message.answer("Вы не подписаны")


# Команда статистики
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Доступ запрещен")
        return

    total_users = db.get_all_users()
    total_count = len(total_users)
    new_users_day = db.get_new_users(1)
    new_users_week = db.get_new_users(7)
    new_users_month = db.get_new_users(30)

    # Сохраняем статистику в Excel
    stats = {
        "Дата": [datetime.now().strftime("%Y-%m-%d")],
        "Всего пользователей": [total_count],
        "Новых за день": [new_users_day],
        "Новых за неделю": [new_users_week],
        "Новых за месяц": [new_users_month]
    }
    df = pd.DataFrame(stats)
    df.to_excel("stats.xlsx", index=False)

    await message.answer(
        f"📊 Статистика:\n"
        f"👤 Всего пользователей: {total_count}\n"
        f"🆕 Новых за день: {new_users_day}\n"
        f"🆕 Новых за неделю: {new_users_week}\n"
        f"🆕 Новых за месяц: {new_users_month}\n"
        f"📊 Статистика сохранена в stats.xlsx"
    )
    await message.answer_document(FSInputFile("stats.xlsx"))


# Команда просмотра БД
@dp.message(Command("viewdb"))
async def cmd_viewdb(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Доступ запрещен")
        return

    users = db.get_all_users()
    response = "📋 Содержимое базы данных:\n"
    for user in users:
        response += f"ID: {user[0]}, Имя: {user[2]}, Дата регистрации: {user[6]}\n"

    await message.answer(response[:4000])  # Ограничение Telegram


# Команда экспорта БД
@dp.message(Command("exportdb"))
async def cmd_exportdb(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Доступ запрещен")
        return

    try:
        filename = db.export_to_csv()
        await message.answer_document(FSInputFile(filename))
    except Exception as e:
        logger.error(f"Ошибка экспорта БД: {e}")
        await message.answer("❌ Ошибка при экспорте базы данных")


# Команда рассылки
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Доступ запрещен")
        return

    await message.answer(
        "📤 Отправьте сообщение для рассылки.\n"
        "Поддерживается текст и файлы."
    )
    await state.set_state(BroadcastState.waiting_for_content)


@dp.message(BroadcastState.waiting_for_content, F.document | F.text)
async def process_broadcast_content(message: Message, state: FSMContext):
    await state.update_data(content=message.html_text, file_id=message.document.file_id if message.document else None)
    await message.answer(
        "Вы уверены, что хотите начать рассылку?\n"
        "Напишите 'да' для подтверждения или 'нет' для отмены."
    )
    await state.set_state(BroadcastState.waiting_for_confirmation)


@dp.message(BroadcastState.waiting_for_confirmation, F.text.lower() == "да")
async def confirm_broadcast(message: Message, state: FSMContext):
    data = await state.get_data()
    content = data.get("content")
    file_id = data.get("file_id")

    users = db.get_all_users()
    success, errors = 0, 0

    for user in users:
        try:
            if file_id:
                await bot.send_document(
                    chat_id=user[0],
                    document=file_id,
                    caption=content
                )
            else:
                await bot.send_message(
                    chat_id=user[0],
                    text=content
                )
            success += 1
        except Exception as e:
            errors += 1
            logger.error(f"Error to {user[0]}: {e}")

    await message.answer(
        f"✅ Рассылка завершена\n"
        f"Успешно: {success}\n"
        f"Ошибок: {errors}"
    )
    await state.clear()


@dp.message(BroadcastState.waiting_for_confirmation, F.text.lower() == "нет")
async def cancel_broadcast(message: Message, state: FSMContext):
    await message.answer("❌ Рассылка отменена")
    await state.clear()


# Основной обработчик неизвестных команд
@dp.message(F.text)  # Фильтр для текстовых сообщений
async def unknown_command(message: Message):
    # Проверяем, начинается ли сообщение с "/" (команда)
    if message.text.startswith("/"):
        commands = get_available_commands(message.from_user.id in ADMIN_IDS)
        await message.answer(
            f"❌ Команда '{message.text}' не найдена.\n"
            f"Используйте /help для просмотра доступных команд:\n"
            f"{commands}"
        )


# Запуск бота
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
    db.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())