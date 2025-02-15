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
                    INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    user.id,
                    user.username,
                    user.first_name,
                    user.last_name,
                    user.language_code,
                    int(user.is_bot),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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

db = Database()

class BroadcastState(StatesGroup):
    waiting_for_content = State()
    waiting_for_confirmation = State()

def get_available_commands(is_admin: bool) -> str:
    user_commands = """
<b>👤 Основные команды:</b>
🔄/start - Начать винное путешествие
🚫/unsubscribe - Выйти из рассылки
🗺️/location - Найти бутик с магией вин
🛍️/shop - Онлайн-магазин
📞/contacts - Связаться с сомелье
🌐/social - Присоединиться к нашему сообществу
💡/help - Показать эту подсказку
"""

    admin_commands = """
<b>🛠 Админ-команды:</b>
/stats - Статистика
/broadcast - Рассылка
/viewdb - Просмотр БД
/exportdb - Экспорт БД
""" if is_admin else ""

    return user_commands + admin_commands

@dp.message(Command("help"))
async def cmd_help(message: Message):
    commands = get_available_commands(message.from_user.id in ADMIN_IDS)
    await message.answer(f"<b>📜 Доступные команды:</b>\n{commands}")

@dp.message(Command("start"))
async def cmd_start(message: Message):
    try:
        if db.add_user(message.from_user):
            if message.from_user.id in ADMIN_IDS:
                text = "👋 <b>Привет, администратор!</b> Используй /help для списка команд"
            else:
                text = (
                    "🍷 <b>Добро пожаловать в мир Drinx!</b> Я ваш персональный гид по винам\n\n"
                    "✨ <b>Что я могу для вас сделать:</b>\n"
                    "🔥 Расскажу об эксклюзивных акциях— секретные скидки, редкие коллекции и дегустации\n\n"
                    "🗺️ Найдете нас за 60 секунд — раскрою адрес бутика с волшебной атмосферой\n\n"
                    "🛍️ Открою <a href='https://vrn.luding.ru/'>онлайн-магазин</a>\n\n"
                    "👪🍷 Познакомлю с нашей дружной семьей в соцсетях\n\n"
                    "📞 Всегда на связи — подскажу контакты для персональных консультаций\n\n"
                    "💡 Все возможности — в команде /help\n\n"
                    "<i>P.S. Хотите подарок? Скажите на кассе «Сырная тарелка🧀✨» "
                    "и получите повышенную скидку!</i>"
                )
            await message.answer(text)
        else:
            await message.answer(
                f"🎉 <b>С возвращением, {message.from_user.first_name}!</b> 🍇\n\n"
                "Ваш доступ к винной вселенной активирован!\n"
                "Нужна помощь? Напишите /help"
            )
    except Exception as e:
        logger.error(f"/start error: {e}")
        await message.answer("⚠️ Ошибка, попробуйте позже")

@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    if db.remove_user(message.from_user.id):
        await message.answer("❌ <b>Вы отписались</b> Я буду ждать вас снова!")
    else:
        await message.answer("ℹ️ Вы не подписаны")

@dp.message(Command("location"))
async def cmd_location(message: Message):
    await message.answer(
        "<b>📍 Наш бутик:</b>\n\n"
        "🏠 <u>Воронеж</u>\n"
        "ул. Загоровского, 7к4\n"
        "⌚ Ежедневно 11:00-23:00\n\n"
        
        "<a href='https://yandex.ru/maps/org/drinx/70384019199/?ll=39.185240%2C51.718339&z=16'>🗺️ Открыть в картах</a>"
    )

@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    await message.answer(
        "<b>🛒 Интернет-магазин Drinx</b>\n\n"
        "🎁 500+ премиальных вин\n"
        "🚚 Доставка по РФ за 3-5 дней\n"
        "💎 Эксклюзивные коллекции\n\n"
        "<a href='https://vrn.luding.ru/'>👉 Перейти в магазин</a>"
    )

@dp.message(Command("contacts"))
async def cmd_contacts(message: Message):
    await message.answer(
        "<b>📞 Контакты:</b>\n\n"
        "☎️ <b>Телефон:</b> +7 (900) 299-91-94 WhatsApp/Telegram\n"
        "⌚ <b>Часы работы:</b> 11:00-23:00\n\n"

    )

@dp.message(Command("social"))
async def cmd_social(message: Message):
    await message.answer(
        "<b>🌍 Мы в соцсетях:</b>\n\n"
        "📸 <a href='https://www.instagram.com/drinx_vrn'>Instagram</a>\n"
        "📘 <a href='https://t.me/drinx_vrn'>Telegram</a>\n"

    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 <b>Доступ запрещен</b>")
        return

    total_users = db.get_all_users()
    total_count = len(total_users)
    new_users_day = db.get_new_users(1)
    new_users_week = db.get_new_users(7)
    new_users_month = db.get_new_users(30)

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
        f"<b>📊 Статистика:</b>\n"
        f"👤 Всего: {total_count}\n"
        f"🆕 За день: {new_users_day}\n"
        f"🆕 За неделю: {new_users_week}\n"
        f"🆕 За месяц: {new_users_month}"
    )
    await message.answer_document(FSInputFile("stats.xlsx"))

@dp.message(Command("viewdb"))
async def cmd_viewdb(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 <b>Доступ запрещен</b>")
        return

    users = db.get_all_users()
    response = "<b>📋 База данных:</b>\n"
    for user in users:
        response += f"ID: {user[0]}, Имя: {user[2]}, Дата: {user[6][:10]}\n"
    await message.answer(response[:4000])

@dp.message(Command("exportdb"))
async def cmd_exportdb(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 <b>Доступ запрещен</b>")
        return

    try:
        filename = db.export_to_csv()
        await message.answer_document(FSInputFile(filename))
    except Exception as e:
        logger.error(f"Export error: {e}")
        await message.answer("❌ Ошибка экспорта")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 <b>Доступ запрещен</b>")
        return

    await message.answer("📤 Отправьте сообщение для рассылки:")
    await state.set_state(BroadcastState.waiting_for_content)

@dp.message(BroadcastState.waiting_for_content, F.document | F.text)
async def process_broadcast_content(message: Message, state: FSMContext):
    content = message.html_text
    file_id = message.document.file_id if message.document else None
    await state.update_data(content=content, file_id=file_id)
    await message.answer("✅ Начать рассылку? Ответьте 'да' или 'нет'")
    await state.set_state(BroadcastState.waiting_for_confirmation)

@dp.message(BroadcastState.waiting_for_confirmation, F.text.lower() == "да")
async def confirm_broadcast(message: Message, state: FSMContext):
    data = await state.get_data()
    users = db.get_all_users()
    success, errors = 0, 0

    for user in users:
        try:
            if data['file_id']:
                await bot.send_document(user[0], data['file_id'], caption=data['content'])
            else:
                await bot.send_message(user[0], data['content'])
            success += 1
        except Exception as e:
            errors += 1
            logger.error(f"Error to {user[0]}: {e}")

    await message.answer(f"✅ Успешно: {success}\n❌ Ошибок: {errors}")
    await state.clear()

@dp.message(BroadcastState.waiting_for_confirmation, F.text.lower() == "нет")
async def cancel_broadcast(message: Message, state: FSMContext):
    await message.answer("❌ Рассылка отменена")
    await state.clear()

@dp.message(F.text)
async def unknown_command(message: Message):
    if message.text.startswith("/"):
        commands = get_available_commands(message.from_user.id in ADMIN_IDS)
        await message.answer(f"❌ Неизвестная команда\n{commands}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
    db.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())