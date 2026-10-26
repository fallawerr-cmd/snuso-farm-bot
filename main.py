import asyncio
import logging
import random
import threading
import aiohttp
import psycopg2
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from flask import Flask

# 🔑 Твой токен от BotFather
TOKEN = "8699329453:AAG8nOspHv22LBk7eYEgK1Nkz0UWtvtXAFA"
# 🌐 Твой URL на Render для самопинга
RENDER_URL = "https://snuso-farm-bot.onrender.com"

# ☁️ Твоя облачная база Supabase (с твоим паролем)
DATABASE_URL = "postgresql://postgres:Qwertyuioplkjhgfdsa1!25June2015@db.royemycrlbvsuwcdmiio.supabase.co:5432/postgres"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== БАЗА ДАННЫХ (PostgreSQL / Supabase) ====================
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# Создаем таблицу игроков в облаке, если её еще нет
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    balance INT DEFAULT 100,
    bushes INT DEFAULT 0,
    normal_snus INT DEFAULT 0,
    rotten_snus INT DEFAULT 0
)
""")
conn.commit()


def get_user(user_id: int):
    cursor.execute("SELECT balance, bushes, normal_snus, rotten_snus FROM users WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id, balance, bushes, normal_snus, rotten_snus) VALUES (%s, 100, 0, 0, 0)", (user_id,))
        conn.commit()
        return {"balance": 100, "bushes": 0, "normal_snus": 0, "rotten_snus": 0}
    return {"balance": user[0], "bushes": user[1], "normal_snus": user[2], "rotten_snus": user[3]}


def update_user(user_id: int, balance: int, bushes: int, normal: int, rotten: int):
    cursor.execute("UPDATE users SET balance = %s, bushes = %s, normal_snus = %s, rotten_snus = %s WHERE user_id = %s", 
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
    elif action == "
