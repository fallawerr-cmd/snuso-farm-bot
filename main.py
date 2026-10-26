import asyncio
import logging
import random
import sqlite3
import threading
import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from flask import Flask

# 🔑 Твой токен от BotFather
TOKEN = "8699329453:AAG8nOspHv22LBk7eYEgK1Nkz0UWtvtXAFA"
# 🌐 Твой URL на Render для самопинга
RENDER_URL = "https://snuso-farm-bot.onrender.com"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== БАЗА ДАННЫХ (SQLite) ====================
conn = sqlite3.connect("game.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 100,
    bushes INTEGER DEFAULT 0,
    normal_snus INTEGER DEFAULT 0,
    rotten_snus INTEGER DEFAULT 0
)
""")
conn.commit()


def get_user(user_id: int):
    cursor.execute("SELECT balance, bushes, normal_snus, rotten_snus FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id, balance, bushes, normal_snus, rotten_snus) VALUES (?, 100, 0, 0, 0)", (user_id,))
        conn.commit()
        return {"balance": 100, "bushes": 0, "normal_snus": 0, "rotten_snus": 0}
    return {"balance": user[0], "bushes": user[1], "normal_snus": user[2], "rotten_snus": user[3]}


def update_user(user_id: int, balance: int, bushes: int, normal: int, rotten: int):
    cursor.execute("UPDATE users SET balance = ?, bushes = ?, normal_snus = ?, rotten_snus = ? WHERE user_id = ?", 
                   (balance, bushes, normal, rotten, user_id))
    conn.commit()


# ==================== КЛАВИАТУРЫ ====================

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton(text="🛍 Магазин", callback_data="menu_shop"),
         InlineKeyboardButton(text="💵 Продать снюс", callback_data="menu_sell")],
        [InlineKeyboardButton(text="📊 Профиль", callback_data="menu_profile")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_shop_menu():
    keyboard = [
        [InlineKeyboardButton(text="🌿 Снюсовый куст 🌱", callback_data="shop_cust")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_buy_menu():
    keyboard = [
        [InlineKeyboardButton(text="🛒 Купить 1 (100₽)", callback_data="buy_1"),
         InlineKeyboardButton(text="📦 Купить 5 (500₽)", callback_data="buy_5")],
        [InlineKeyboardButton(text="💎 Купить на все", callback_data="buy_all")],
        [InlineKeyboardButton(text="⬅️ Назад в магазин", callback_data="menu_shop")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_sell_menu():
    keyboard = [
        [InlineKeyboardButton(text="💸 Продать весь нормальный снюс", callback_data="action_sell")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ==================== ОБРАБОТЧИКИ КОМАНД И КНОПОК ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = get_user(message.from_user.id)
    text = (
        "🌲 **Добро пожаловать на Снюсовую Ферму!**\n\n"
        f"💰 Баланс: `{user['balance']} руб.`\n"
        f"🌿 Кустов на ферме: `{user['bushes']}`\n"
        f"📦 Нормальный снюс: `{user['normal_snus']} шт.`\n"
        f"🤢 Гнилой снюс: `{user['rotten_snus']} шт.`\n\n"
        "Выбирай раздел ниже:"
    )
    try:
        photo = FSInputFile("shop.png")
        await message.answer_photo(photo=photo, caption=text, reply_markup=get_main_menu(), parse_mode="Markdown")
    except:
        await message.answer(text=text, reply_markup=get_main_menu(), parse_mode="Markdown")


@dp.callback_query(F.data == "back_main")
async def callback_back_main(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    text = (
        "🌲 **Главное меню Снюсовой Фермы:**\n\n"
        f"💰 Баланс: `{user['balance']} руб.`\n"
        f"🌿 Кустов: `{user['bushes']}`"
    )
    try:
        photo = FSInputFile("shop.png")
        await callback.message.edit_media(
            media=types.InputMediaPhoto(media=photo, caption=text, parse_mode="Markdown"),
            reply_markup=get_main_menu()
        )
    except:
        await callback.message.edit_text(text=text, reply_markup=get_main_menu(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "menu_shop")
async def callback_shop(callback: types.CallbackQuery):
    text = "🛍 **Магазин фермы**\n\nВыбери товар для покупки:"
    try:
        photo = FSInputFile("cust.png")
        await callback.message.edit_media(
            media=types.InputMediaPhoto(media=photo, caption=text, parse_mode="Markdown"),
            reply_markup=get_shop_menu()
        )
    except:
        await callback.message.edit_text(text=text, reply_markup=get_shop_menu(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "shop_cust")
async def callback_shop_cust(callback: types.CallbackQuery):
    text = (
        "🌿 **Снюсовый куст**\n\n"
        "• Стоимость: `100 руб.`\n"
        "• Производит до 4 снюсов (каждые 15 минут)\n"
        "• Шанс 25% на гнилой пакетик"
    )
    try:
        photo = FSInputFile("cust.png")
        await callback.message.edit_media(
            media=types.InputMediaPhoto(media=photo, caption=text, parse_mode="Markdown"),
            reply_markup=get_buy_menu()
        )
    except:
        await callback.message.edit_text(text=text, reply_markup=get_buy_menu(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def callback_buy(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    action = callback.data

    price_per_one = 100
    amount = 0

    if action == "buy_1":
        amount = 1
    elif action == "buy_5":
        amount = 5
    elif action == "buy_all":
        amount = user["balance"] // price_per_one

    total_cost = amount * price_per_one

    if amount <= 0:
        await callback.answer("❌ Недостаточно средств для покупки!", show_alert=True)
        return

    if user["balance"] >= total_cost:
        user["balance"] -= total_cost
        user["bushes"] += amount
        update_user(user_id, user["balance"], user["bushes"], user["normal_snus"], user["rotten_snus"])
        await callback.answer(f"✅ Успешно куплено кустов: {amount} шт. за {total_cost}₽!", show_alert=True)
        
        text = f"🌿 **Снюсовый куст**\n\nКуплено! Твой баланс: `{user['balance']} руб.`\nКустов на ферме: `{user['bushes']}`"
        try:
            photo = FSInputFile("cust.png")
            await callback.message.edit_media(
                media=types.InputMediaPhoto(media=photo, caption=text, parse_mode="Markdown"),
                reply_markup=get_buy_menu()
            )
        except:
            await callback.message.edit_text(text=text, reply_markup=get_buy_menu(), parse_mode="Markdown")
    else:
        await callback.answer("❌ Не хватает денег!", show_alert=True)


@dp.callback_query(F.data == "menu_sell")
async def callback_sell_menu(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    text = (
        "💵 **Рынок сбыта**\n\n"
        f"📦 У тебя в инвентаре нормального снюса: `{user['normal_snus']} шт.`\n"
        f"💰 Цена продажи: `50 руб. / шт.`"
    )
    try:
        photo = FSInputFile("sell.png")
        await callback.message.edit_media(
            media=types.InputMediaPhoto(media=photo, caption=text, parse_mode="Markdown"),
            reply_markup=get_sell_menu()
        )
    except:
        await callback.message.edit_text(text=text, reply_markup=get_sell_menu(), parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "action_sell")
async def callback_action_sell(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    normal_count = user["normal_snus"]

    if normal_count > 0:
        earned = normal_count * 50
        user["balance"] += earned
        user["normal_snus"] = 0
        update_user(user_id, user["balance"], user["bushes"], user["normal_snus"], user["rotten_snus"])
        
        text = f"💵 Ты успешно продал `{normal_count} шт.` снюса и поднял `{earned} руб.`!\nБаланс: `{user['balance']} руб.`"
        await callback.answer(f"Продано на {earned}₽!", show_alert=True)
        
        try:
            photo = FSInputFile("sell.png")
            await callback.message.edit_media(
                media=types.InputMediaPhoto(media=photo, caption=text, parse_mode="Markdown"),
                reply_markup=get_sell_menu()
            )
        except:
            await callback.message.edit_text(text=text, reply_markup=get_sell_menu(), parse_mode="Markdown")
    else:
        await callback.answer("❌ У тебя нет нормального снюса для продажи!", show_alert=True)


@dp.callback_query(F.data == "menu_profile")
async def callback_profile(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    text = (
        f"📊 **Твой профиль:**\n\n"
        f"💰 Деньги: `{user['balance']} руб.`\n"
        f"🌱 Кустов: `{user['bushes']}`\n"
        f"📦 Нормальный снюс: `{user['normal_snus']} шт.`\n"
        f"🤢 Гнилой снюс: `{user['rotten_snus']} шт.`"
    )
    await callback.answer(text, show_alert=True)


# ==================== ФОНОВЫЙ РОСТ СНЮСА (каждые 15 мин) ====================
async def grow_snus_loop():
    while True:
        await asyncio.sleep(900)
        cursor.execute("SELECT user_id, bushes, normal_snus, rotten_snus FROM users WHERE bushes > 0")
        all_users = cursor.fetchall()

        for row in all_users:
            user_id, bushes, normal, rotten = row
            for _ in range(bushes * 4):
                is_rotten = random.randint(1, 4) == 1
                if is_rotten:
                    rotten += 1
                else:
                    normal += 1
            cursor.execute("UPDATE users SET normal_snus = ?, rotten_snus = ? WHERE user_id = ?", (normal, rotten, user_id))
            conn.commit()
        logging.info("Урожай снюса обновился!")


# ==================== САМОПИНГ (Каждые 30 секунд от сна) ====================
async def self_ping_loop():
    await asyncio.sleep(10)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(RENDER_URL) as response:
                    logging.info(f"Самопинг выполнен успешно, статус: {response.status}")
            except Exception as e:
                logging.info(f"Ошибка самопинга: {e}")
            await asyncio.sleep(30)


# ==================== FLASK-СЕРВЕР (Для Render.com) ====================
app = Flask(__name__)

@app.route("/")
def index():
    return "Snus Farm Bot is running 24/7!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)


# ==================== ЗАПУСК ====================
async def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    asyncio.create_task(grow_snus_loop())
    asyncio.create_task(self_ping_loop())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
