import os
import logging
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, FSInputFile, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder
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
    default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# База данных
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

    def get_user_count_by_date(self):
        with self.conn:
            cursor = self.conn.execute("""
                SELECT date(date_joined), COUNT(*) FROM users GROUP BY date(date_joined)
            """)
            return cursor.fetchall()

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


# Состояния для рассылки
class BroadcastState(StatesGroup):
    waiting_for_content = State()
    waiting_for_confirmation = State()


# Создание инлайн-клавиатуры
def create_inline_keyboard(is_admin: bool, show_start: bool = False, only_back: bool = False) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if only_back:
        builder.button(text="🔙 Назад", callback_data="back")
        builder.adjust(1)
        return builder.as_markup()

    # Основные кнопки для всех пользователей
    buttons = [
        ("🗺️ Бутик", "location"),
        ("🛍️ Магазин", "shop"),
        ("📞 Контакты", "contacts"),
        ("🌐 Соцсети", "social"),
        ("🎁 Подарок", "gift"),
        ("💡 Помощь", "help"),
    ]

    if show_start:
        buttons.insert(0, ("🔄 Начать", "start"))

    # Кнопка отписки
    if not show_start:
        buttons.append(("🚫 Отписаться", "unsubscribe"))

    # Добавляем кнопки администратора
    if is_admin:
        admin_buttons = [
            ("📊 Статистика", "stats"),
            ("📤 Рассылка", "broadcast"),
            ("👁️ БД", "viewdb"),
            ("📁 Экспорт", "exportdb")
        ]
        buttons.extend(admin_buttons)

    # Кнопка "Назад"
    buttons.append(("🔙 Назад", "back"))

    # Создаем кнопки и настраиваем расположение
    for text, callback_data in buttons:
        builder.button(text=text, callback_data=callback_data)

    builder.adjust(2, 2, 2, 2)  # По 2 кнопки в ряду
    return builder.as_markup()


# Генерация текста с командами
def get_available_commands(is_admin: bool) -> str:
    user_commands = """
<b>👤 Основные команды:</b>
🔄/start - Начать винное путешествие
🚫/unsubscribe - Выйти из рассылки
🗺️/location - Найти бутик
🛍️/shop - Онлайн-магазин
📞/contacts - Контакты
🌐/social - Соцсети
🎁/gift - Получить подарок
💡/help - Помощь
"""

    admin_commands = """
<b>🛠 Админ-команды:</b>
/stats - Статистика
/broadcast - Рассылка
/viewdb - Просмотр БД
/exportdb - Экспорт БД
""" if is_admin else ""

    return user_commands + admin_commands


# Приветственное сообщение
async def send_welcome(message: Message, is_admin: bool, show_start: bool = False):
    keyboard = create_inline_keyboard(is_admin, show_start)
    if is_admin:
        text = "👋 <b>Привет, администратор!</b> Используй кнопки ниже или /help"
    else:
        text = (
            "🍷 <b>Добро пожаловать в мир Drinx!</b> Я ваш персональный гид по винам\n\n"
            "✨ <b>Что я могу для вас сделать:</b>\n"
            "🔥 Расскажу об эксклюзивных акциях\n"
            "🗺️ Найдете наш бутик за 60 секунд\n"
            "🛍️ Открою онлайн-магазин\n"
            "👪🍷 Познакомлю с нашей семьей в соцсетях\n"
            "📞 Всегда на связи\n\n"
            "<i>P.S. Хотите подарок? Нажмите кнопку 🎁 Подарок!</i>"
        )
    await message.answer(text, reply_markup=keyboard)


# Информация о магазине
async def send_shop_info(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(
        "<b>🛒 Интернет-магазин Drinx</b>\n\n"
        "🎁 500+ премиальных вин\n"
        "🚚 Доставка по РФ за 3-5 дней\n"
        "💎 Эксклюзивные коллекции\n\n"
        "<a href='https://vrn.luding.ru/'>👉 Перейти в магазин</a>",
        reply_markup=create_inline_keyboard(is_admin, only_back=True)
    )


# Информация о местоположении
async def send_location_info(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(
        "<b>📍 Наш бутик:</b>\n\n"
        "🏠 <u>Воронеж</u>\n"
        "ул. Загоровского, 7к4\n"
        "⌚ Ежедневно 11:00-23:00\n\n"
        "<a href='https://yandex.ru/maps/org/drinx/70384019199/?ll=39.185240%2C51.718339&z=16'>🗺️ Открыть в картах</a>",
        reply_markup=create_inline_keyboard(is_admin, only_back=True)
    )


# Контактная информация
async def send_contacts_info(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(
        "<b>📞 Контакты:</b>\n\n"
        "☎️ <b>Телефон:</b> +7 (900) 299-91-94 WhatsApp/Telegram\n"
        "⌚ <b>Часы работы:</b> 11:00-23:00",
        reply_markup=create_inline_keyboard(is_admin, only_back=True)
    )


# Информация о соцсетях
async def send_social_info(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(
        "<b>🌍 Мы в соцсетях:</b>\n\n"
        "📸 <a href='https://www.instagram.com/drinx_vrn'>Instagram</a>\n"
        "📘 <a href='https://t.me/drinx_vrn'>Telegram</a>",
        reply_markup=create_inline_keyboard(is_admin, only_back=True)
    )


# Подарок
async def send_gift_info(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(
        "🎁 <b>Ваш подарок:</b>\n\n"
        "Скажите на кассе «Сырная тарелка🧀✨» и получите повышенную скидку!",
        reply_markup=create_inline_keyboard(is_admin, only_back=True)
    )


# Обработчики команд
@dp.message(Command("help"))
async def cmd_help(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    commands = get_available_commands(is_admin)
    keyboard = create_inline_keyboard(is_admin)
    await message.answer(f"<b>📜 Доступные команды:</b>\n{commands}", reply_markup=keyboard)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    try:
        is_admin = message.from_user.id in ADMIN_IDS
        if db.add_user(message.from_user):
            await send_welcome(message, is_admin, show_start=False)
        else:
            await send_welcome(message, is_admin, show_start=True)
    except Exception as e:
        logger.error(f"/start error: {e}")
        await message.answer("⚠️ Ошибка, попробуйте позже")


@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    await send_shop_info(message)


@dp.message(Command("location"))
async def cmd_location(message: Message):
    await send_location_info(message)


@dp.message(Command("contacts"))
async def cmd_contacts(message: Message):
    await send_contacts_info(message)


@dp.message(Command("social"))
async def cmd_social(message: Message):
    await send_social_info(message)


@dp.message(Command("gift"))
async def cmd_gift(message: Message):
    await send_gift_info(message)


@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    if db.remove_user(message.from_user.id):
        await message.answer("❌ <b>Вы отписались</b> Я буду ждать вас снова!",
                             reply_markup=create_inline_keyboard(False, show_start=True))
    else:
        await message.answer("ℹ️ Вы не подписаны", reply_markup=create_inline_keyboard(False, show_start=True))


# Админские команды с дополнительным параметром user для проверки прав
@dp.message(Command("stats"))
async def cmd_stats(message: Message, user: types.User = None):
    actual_user = user if user is not None else message.from_user
    if actual_user.id not in ADMIN_IDS:
        await message.answer("🚫 <b>Доступ запрещен</b>")
        return

    total_users = db.get_all_users()
    total_count = len(total_users)
    new_users_day = db.get_new_users(1)
    new_users_week = db.get_new_users(7)
    new_users_month = db.get_new_users(30)

    # График прироста пользователей
    user_data = db.get_user_count_by_date()
    dates = [row[0] for row in user_data]
    counts = [row[1] for row in user_data]

    plt.figure(figsize=(10, 5))
    plt.plot(dates, counts, marker='o')
    plt.title("Прирост пользователей")
    plt.xlabel("Дата")
    plt.ylabel("Количество пользователей")
    plt.grid(True)
    plt.savefig("stats_graph.png")
    plt.close()

    stats_text = (
        f"<b>📊 Статистика:</b>\n"
        f"👤 Всего: {total_count}\n"
        f"🆕 За день: {new_users_day}\n"
        f"🆕 За неделю: {new_users_week}\n"
        f"🆕 За месяц: {new_users_month}"
    )

    await message.answer_photo(FSInputFile("stats_graph.png"), caption=stats_text)
    await message.answer_document(FSInputFile("stats_graph.png"))


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext, user: types.User = None):
    actual_user = user if user is not None else message.from_user
    if actual_user.id not in ADMIN_IDS:
        await message.answer("🚫 <b>Доступ запрещен</b>")
        return
    await message.answer("📤 Введите сообщение для рассылки:")
    await state.set_state(BroadcastState.waiting_for_content)


@dp.message(BroadcastState.waiting_for_content)
async def process_broadcast_content(message: Message, state: FSMContext):
    await state.update_data(content=message.text)
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="broadcast_confirm")
    builder.button(text="❌ Отменить", callback_data="broadcast_cancel")
    builder.adjust(2)
    await message.answer("Подтвердите рассылку:", reply_markup=builder.as_markup())
    await state.set_state(BroadcastState.waiting_for_confirmation)


@dp.callback_query(BroadcastState.waiting_for_confirmation, F.data == "broadcast_confirm")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    content = data.get("content")
    users = db.get_all_users()
    for user in users:
        try:
            await bot.send_message(user[0], content)
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user[0]}: {e}")
    await callback.message.answer("✅ Рассылка завершена!")
    await state.clear()


@dp.callback_query(BroadcastState.waiting_for_confirmation, F.data == "broadcast_cancel")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("❌ Рассылка отменена.")
    await state.clear()


@dp.message(Command("viewdb"))
async def cmd_viewdb(message: Message, user: types.User = None):
    actual_user = user if user is not None else message.from_user
    if actual_user.id not in ADMIN_IDS:
        await message.answer("🚫 <b>Доступ запрещен</b>")
        return
    users = db.get_all_users()
    if not users:
        await message.answer("ℹ️ В базе данных нет пользователей.")
        return
    users_text = "\n".join([
        f"👤 ID: {user[0]}, Имя: {user[2]}, Ник: @{user[1]}, Дата: {user[6]}"
        for user in users
    ])
    await message.answer(f"<b>📁 Пользователи в базе данных:</b>\n{users_text}")


@dp.message(Command("exportdb"))
async def cmd_exportdb(message: Message, user: types.User = None):
    actual_user = user if user is not None else message.from_user
    if actual_user.id not in ADMIN_IDS:
        await message.answer("🚫 <b>Доступ запрещен</b>")
        return
    try:
        file_path = db.export_to_csv()
        await message.answer_document(FSInputFile(file_path), caption="📁 <b>Экспорт базы данных завершен.</b>")
    except Exception as e:
        logger.error(f"Ошибка при экспорте базы данных: {e}")
        await message.answer("⚠️ Ошибка при экспорте базы данных.")


# Обработчики кнопок
@dp.callback_query(F.data == "start")
async def handle_start(callback: CallbackQuery):
    await cmd_start(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "shop")
async def handle_shop(callback: CallbackQuery):
    await send_shop_info(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "location")
async def handle_location(callback: CallbackQuery):
    await send_location_info(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "contacts")
async def handle_contacts(callback: CallbackQuery):
    await send_contacts_info(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "social")
async def handle_social(callback: CallbackQuery):
    await send_social_info(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "gift")
async def handle_gift(callback: CallbackQuery):
    await send_gift_info(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "help")
async def handle_help(callback: CallbackQuery):
    await cmd_help(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "unsubscribe")
async def handle_unsubscribe(callback: CallbackQuery):
    await cmd_unsubscribe(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "stats")
async def handle_stats(callback: CallbackQuery):
    # Передаём callback.from_user для корректной проверки прав
    await cmd_stats(callback.message, user=callback.from_user)
    await callback.answer()


@dp.callback_query(F.data == "broadcast")
async def handle_broadcast(callback: CallbackQuery, state: FSMContext):
    await cmd_broadcast(callback.message, state, user=callback.from_user)
    await callback.answer()


@dp.callback_query(F.data == "viewdb")
async def handle_viewdb(callback: CallbackQuery):
    await cmd_viewdb(callback.message, user=callback.from_user)
    await callback.answer()


@dp.callback_query(F.data == "exportdb")
async def handle_exportdb(callback: CallbackQuery):
    await cmd_exportdb(callback.message, user=callback.from_user)
    await callback.answer()


@dp.callback_query(F.data == "back")
async def handle_back(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    await send_welcome(callback.message, is_admin)
    await callback.answer()


# Запуск бота
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
    db.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
