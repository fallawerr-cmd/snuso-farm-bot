import asyncio
import logging
import os
import random
import threading
import time
from contextlib import contextmanager

import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (BufferedInputFile, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto)

from flask import Flask
from psycopg2 import pool

# ---------------------------------------------------------------- конфиг
# Значения оставлены как были; на Render можно переопределить через env.
TOKEN = os.getenv("TOKEN", "8699329453:AAG8nOspHv22LBk7eYEgK1Nkz0UWtvtXAFA")
RENDER_URL = os.getenv("RENDER_URL", "https://snuso-farm-bot.onrender.com")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:Qwertyuioplkjhgfdsa1!25June2015@db.royemycrlbvsuwcdmiio.supabase.co:5432/postgres",
)

BUSH_PRICE = 100
SNUS_PRICE = 50
SNUS_PER_BUSH = 4
ROTTEN_CHANCE = 0.25
GROW_INTERVAL = 15 * 60  # секунд

RAW = "https://raw.githubusercontent.com/fallawerr-cmd/snuso-farm-bot/main"
IMAGES = {
    "shop": f"{RAW}/shop.jpg",
    "cust": f"{RAW}/cust.jpg",
    "sell": f"{RAW}/sell.jpg",
}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("snus")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------------------------------------------------------------- БД
db_pool = pool.ThreadedConnectionPool(1, 5, DATABASE_URL)


@contextmanager
def db():
    conn = db_pool.getconn()
    try:
        with conn:  # commit / rollback
            with conn.cursor() as cur:
                yield cur
    finally:
        db_pool.putconn(conn)


def init_db():
    with db() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INT DEFAULT 100,
                bushes INT DEFAULT 0,
                normal_snus INT DEFAULT 0,
                rotten_snus INT DEFAULT 0
            )
            """
        )


def _get_user(user_id: int) -> dict:
    with db() as cur:
        cur.execute(
            "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,)
        )
        cur.execute(
            "SELECT balance, bushes, normal_snus, rotten_snus FROM users WHERE user_id = %s",
            (user_id,),
        )
        b, bu, n, r = cur.fetchone()
    return {"balance": b, "bushes": bu, "normal": n, "rotten": r}


def _buy_bushes(user_id: int, amount: int) -> bool:
    """Атомарная покупка: баланс не уйдёт в минус даже при быстрых кликах."""
    cost = amount * BUSH_PRICE
    with db() as cur:
        cur.execute(
            """
            UPDATE users SET balance = balance - %s, bushes = bushes + %s
            WHERE user_id = %s AND balance >= %s
            """,
            (cost, amount, user_id, cost),
        )
        return cur.rowcount == 1


def _sell_normal(user_id: int):
    """Возвращает (сколько продано, новый баланс) или None."""
    with db() as cur:
        cur.execute(
            """
            WITH old AS (
                SELECT normal_snus FROM users WHERE user_id = %s FOR UPDATE
            )
            UPDATE users
            SET balance = balance + old.normal_snus * %s, normal_snus = 0
            FROM old
            WHERE users.user_id = %s AND old.normal_snus > 0
            RETURNING old.normal_snus, users.balance
            """,
            (user_id, SNUS_PRICE, user_id),
        )
        return cur.fetchone()


def _grow_all():
    with db() as cur:
        cur.execute("SELECT user_id, bushes FROM users WHERE bushes > 0")
        rows = cur.fetchall()
        for user_id, bushes in rows:
            total = bushes * SNUS_PER_BUSH
            rotten = sum(random.random() < ROTTEN_CHANCE for _ in range(total))
            normal = total - rotten
            cur.execute(
                """
                UPDATE users SET normal_snus = normal_snus + %s,
                                 rotten_snus = rotten_snus + %s
                WHERE user_id = %s
                """,
                (normal, rotten, user_id),
            )
    return len(rows)


async def get_user(user_id):
    return await asyncio.to_thread(_get_user, user_id)


# ---------------------------------------------------------------- картинки
# Порядок: file_id -> файл рядом с ботом -> ссылка GitHub -> скачать и залить.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_file_ids: dict[str, str] = {}
_bytes_cache: dict[str, BufferedInputFile] = {}


async def _download(key: str) -> BufferedInputFile:
    if key not in _bytes_cache:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                IMAGES[key], timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                r.raise_for_status()
                data = await r.read()
        _bytes_cache[key] = BufferedInputFile(data, filename=f"{key}.jpg")
    return _bytes_cache[key]


async def _candidates(key: str):
    if key in _file_ids:
        yield _file_ids[key]
    path = os.path.join(BASE_DIR, f"{key}.jpg")
    if os.path.exists(path):
        yield FSInputFile(path)
    yield IMAGES[key]
    try:
        yield await _download(key)
    except Exception as e:
        log.warning("не скачалась картинка %s: %s", key, e)


def _remember(key: str, msg):
    if isinstance(msg, types.Message) and msg.photo:
        _file_ids[key] = msg.photo[-1].file_id


def _forget(key: str, photo):
    if isinstance(photo, str) and _file_ids.get(key) == photo:
        _file_ids.pop(key, None)  # протухший file_id


async def show(target, key: str, text: str, kb: InlineKeyboardMarkup):
    """Экран с картинкой. target: Message или CallbackQuery."""
    is_cb = isinstance(target, types.CallbackQuery)
    message = target.message if is_cb else target
    last_err = None

    # 1) правим текущее сообщение (картинка остаётся прикреплённой)
    if is_cb:
        async for photo in _candidates(key):
            try:
                res = await message.edit_media(
                    InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"),
                    reply_markup=kb,
                )
                _remember(key, res)
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
                last_err = e
                _forget(key, photo)
                log.warning("edit_media (%s) не вышел: %s", key, e)
                if "no media" in str(e) or "message to edit" in str(e):
                    break
            except Exception as e:
                last_err = e
                log.warning("edit_media (%s): %s", key, e)
        try:
            await message.delete()
        except Exception:
            pass

    # 2) новое сообщение с картинкой
    async for photo in _candidates(key):
        try:
            msg = await message.answer_photo(
                photo, caption=text, reply_markup=kb, parse_mode="HTML"
            )
            _remember(key, msg)
            return
        except Exception as e:
            last_err = e
            _forget(key, photo)
            log.warning("answer_photo (%s) не вышел: %s", key, e)

    # 3) крайний случай - текст
    log.error("Картинка %s не отправилась, шлю текст. Причина: %s", key, last_err)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
def kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
        ]
    )


MAIN_KB = kb(
    [
        [("🛍 Магазин", "menu_shop"), ("💵 Продать снюс", "menu_sell")],
        [("📊 Профиль", "menu_profile")],
    ]
)
SHOP_KB = kb([[("🌿 Снюсовый куст", "shop_cust")], [("⬅️ Назад", "back_main")]])
BUY_KB = kb(
    [
        [(f"🛒 Купить 1 ({BUSH_PRICE}₽)", "buy_1"), (f"📦 Купить 5 ({BUSH_PRICE * 5}₽)", "buy_5")],
        [("💎 Купить на все деньги", "buy_all")],
        [("⬅️ В магазин", "menu_shop")],
    ]
)
SELL_KB = kb([[("💸 Продать весь нормальный снюс", "action_sell")], [("⬅️ Назад", "back_main")]])
PROFILE_KB = kb([[("⬅️ Назад", "back_main")]])


# ---------------------------------------------------------------- тексты
next_grow_at = time.time() + GROW_INTERVAL


def grow_timer() -> str:
    left = max(0, int(next_grow_at - time.time()))
    return f"{left // 60}:{left % 60:02d}"


def main_text(u):
    return (
        "🌲 <b>Снюсовая Ферма</b>\n\n"
        f"💰 Баланс: <b>{u['balance']} ₽</b>\n"
        f"🌿 Кустов: <b>{u['bushes']}</b>\n"
        f"📦 Нормальный снюс: <b>{u['normal']}</b>\n"
        f"🤢 Гнилой снюс: <b>{u['rotten']}</b>\n\n"
        f"⏳ Следующий урожай через <b>{grow_timer()}</b>\n"
        "Выбирай раздел:"
    )


# ---------------------------------------------------------------- хендлеры
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    u = await get_user(message.from_user.id)
    await show(message, "shop", main_text(u), MAIN_KB)


@dp.callback_query(F.data == "back_main")
async def cb_back(cb: types.CallbackQuery):
    u = await get_user(cb.from_user.id)
    await show(cb, "shop", main_text(u), MAIN_KB)
    await cb.answer()


@dp.callback_query(F.data == "menu_shop")
async def cb_shop(cb: types.CallbackQuery):
    u = await get_user(cb.from_user.id)
    text = f"🛍 <b>Магазин фермы</b>\n\n💰 Баланс: <b>{u['balance']} ₽</b>\nВыбери товар:"
    await show(cb, "cust", text, SHOP_KB)
    await cb.answer()


async def cust_text(u, note=""):
    return (
        f"🌿 <b>Снюсовый куст</b>\n\n"
        f"• Цена: <b>{BUSH_PRICE} ₽</b>\n"
        f"• Даёт до {SNUS_PER_BUSH} снюса каждые {GROW_INTERVAL // 60} минут\n"
        f"• Шанс гнилого пакетика: {int(ROTTEN_CHANCE * 100)}%\n\n"
        f"💰 Баланс: <b>{u['balance']} ₽</b>\n"
        f"🌱 Твоих кустов: <b>{u['bushes']}</b>"
        + (f"\n\n{note}" if note else "")
    )


@dp.callback_query(F.data == "shop_cust")
async def cb_shop_cust(cb: types.CallbackQuery):
    u = await get_user(cb.from_user.id)
    await show(cb, "cust", await cust_text(u), BUY_KB)
    await cb.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def cb_buy(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    u = await get_user(user_id)
    action = cb.data

    if action == "buy_1":
        amount = 1
    elif action == "buy_5":
        amount = 5
    else:
        amount = u["balance"] // BUSH_PRICE

    if amount <= 0 or u["balance"] < amount * BUSH_PRICE:
        await cb.answer("❌ Не хватает денег!", show_alert=True)
        return

    ok = await asyncio.to_thread(_buy_bushes, user_id, amount)
    if not ok:
        await cb.answer("❌ Не хватает денег!", show_alert=True)
        return

    u = await get_user(user_id)
    note = f"✅ Куплено кустов: <b>{amount}</b> за <b>{amount * BUSH_PRICE} ₽</b>"
    await show(cb, "cust", await cust_text(u, note), BUY_KB)
    await cb.answer("✅ Куплено!")


@dp.callback_query(F.data == "menu_sell")
async def cb_sell_menu(cb: types.CallbackQuery):
    u = await get_user(cb.from_user.id)
    text = (
        "💵 <b>Рынок сбыта</b>\n\n"
        f"📦 Нормального снюса: <b>{u['normal']}</b>\n"
        f"💰 Цена: <b>{SNUS_PRICE} ₽ / шт.</b>\n"
        f"💵 Можно выручить: <b>{u['normal'] * SNUS_PRICE} ₽</b>"
    )
    await show(cb, "sell", text, SELL_KB)
    await cb.answer()


@dp.callback_query(F.data == "action_sell")
async def cb_sell(cb: types.CallbackQuery):
    res = await asyncio.to_thread(_sell_normal, cb.from_user.id)
    if not res:
        await cb.answer("❌ Нет нормального снюса для продажи!", show_alert=True)
        return
    count, balance = res
    text = (
        "💵 <b>Рынок сбыта</b>\n\n"
        f"✅ Продано: <b>{count} шт.</b> на <b>{count * SNUS_PRICE} ₽</b>\n"
        f"💰 Баланс: <b>{balance} ₽</b>"
    )
    await show(cb, "sell", text, SELL_KB)
    await cb.answer(f"Продано на {count * SNUS_PRICE}₽!")


@dp.callback_query(F.data == "menu_profile")
async def cb_profile(cb: types.CallbackQuery):
    u = await get_user(cb.from_user.id)
    text = (
        "📊 <b>Твой профиль</b>\n\n"
        f"💰 Деньги: <b>{u['balance']} ₽</b>\n"
        f"🌱 Кустов: <b>{u['bushes']}</b>\n"
        f"📦 Нормальный снюс: <b>{u['normal']}</b>\n"
        f"🤢 Гнилой снюс: <b>{u['rotten']}</b>\n\n"
        f"⏳ Следующий урожай через <b>{grow_timer()}</b>"
    )
    await show(cb, "shop", text, PROFILE_KB)
    await cb.answer()


# ---------------------------------------------------------------- фон
async def grow_snus_loop():
    global next_grow_at
    while True:
        next_grow_at = time.time() + GROW_INTERVAL
        await asyncio.sleep(GROW_INTERVAL)
        try:
            n = await asyncio.to_thread(_grow_all)
            log.info("Урожай выдан %s игрокам", n)
        except Exception:
            log.exception("Ошибка в цикле роста")


async def keep_alive_loop():
    """Пингуем сам себя, чтобы Render не усыплял сервис."""
    await asyncio.sleep(60)
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_URL, timeout=aiohttp.ClientTimeout(total=15)):
                    pass
        except Exception as e:
            log.warning("keep-alive не удался: %s", e)
        await asyncio.sleep(600)


app = Flask(__name__)


@app.route("/")
def index():
    return "Snus farm is running"


def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))


async def main():
    init_db()
    log.info("BASE_DIR=%s files=%s", BASE_DIR, os.listdir(BASE_DIR))
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.create_task(grow_snus_loop())
    asyncio.create_task(keep_alive_loop())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
