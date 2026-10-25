import asyncio
import logging
import random
import sqlite3
import threading
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask

# 🔑 Твой токен от BotFather
TOKEN = "8699329453:AAG8nOspHv22LBk7eYEgK1Nkz0UWtvtXAFA"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== БАЗА ДАННЫХ (SQLite) ====================
conn = sqlite3.connect("game.db", check_same_thread=False)
cursor = conn.cursor()

# Создаем таблицу игроков, если её нет
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
  """Получает данные игрока из базы.

  Если игрока нет — создает с балансом 100 руб.
  """
  cursor.execute(
      "SELECT balance, bushes, normal_snus, rotten_snus FROM users WHERE"
      " user_id = ?",
      (user_id,),
  )
  user = cursor.fetchone()
  if not user:
    cursor.execute(
        "INSERT INTO users (user_id, balance, bushes, normal_snus, rotten_snus)"
        " VALUES (?, 100, 0, 0, 0)",
        (user_id,),
    )
    conn.commit()
    return {"balance": 100, "bushes": 0, "normal_snus": 0, "rotten_snus": 0}
  return {
      "balance": user[0],
      "bushes": user[1],
      "normal_snus": user[2],
      "rotten_snus": user[3],
  }


def update_user(user_id: int, balance: int, bushes: int, normal: int, rotten: int):
  """Обновляет данные игрока в базе."""
  cursor.execute(
      "UPDATE users SET balance = ?, bushes = ?, normal_snus = ?, rotten_snus ="
      " ? WHERE user_id = ?",
      (balance, bushes, normal, rotten, user_id),
  )
  conn.commit()


# ==================== КОМАНДЫ БОТА ====================


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
  user = get_user(message.from_user.id)
  text = (
      "🌲 **Добро пожаловать на Снюсовую Ферму!**\n\n"
      f"💰 Баланс: `{user['balance']} руб.`\n"
      f"🌿 Кустов на ферме: `{user['bushes']}`\n"
      f"🎒 Инвентарь:\n"
      f"   — Нормальный снюс: {user['normal_snus']} шт.\n"
      f"   — Гнилой снюс: {user['rotten_snus']} шт.\n\n"
      "📜 **Команды:**\n"
      "🔹 /buy — Купить снюсовый куст (100 руб.)\n"
      "🔹 /sell — Продать нормальный снюс (50 руб./шт.)\n"
      "🔹 /status — Проверить баланс и урожай"
  )
  await message.answer(text, parse_mode="Markdown")


@dp.message(Command("status"))
async def cmd_status(message: types.Message):
  user = get_user(message.from_user.id)
  text = (
      f"📊 **Твой профиль:**\n\n"
      f"💰 Деньги: `{user['balance']} руб.`\n"
      f"🌱 Кустов: `{user['bushes']}`\n"
      f"📦 Нормальный снюс: `{user['normal_snus']} шт.`\n"
      f"🤢 Гнилой снюс: `{user['rotten_snus']} шт.`"
  )
  await message.answer(text, parse_mode="Markdown")


@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
  user_id = message.from_user.id
  user = get_user(user_id)
  cost = 100

  if user["balance"] >= cost:
    user["balance"] -= cost
    user["bushes"] += 1
    update_user(
        user_id,
        user["balance"],
        user["bushes"],
        user["normal_snus"],
        user["rotten_snus"],
    )
    await message.answer(
        f"✅ Ты купил снюсовый куст за 100 руб.!\nТеперь у тебя кустов:"
        f" {user['bushes']}"
    )
  else:
    await message.answer(
        f"❌ Не хватает денег! Куст стоит 100 руб., а у тебя всего"
        f" {user['balance']} руб."
    )


@dp.message(Command("sell"))
async def cmd_sell(message: types.Message):
  user_id = message.from_user.id
  user = get_user(user_id)
  normal_count = user["normal_snus"]

  if normal_count > 0:
    earned = normal_count * 50
    user["balance"] += earned
    user["normal_snus"] = 0
    update_user(
        user_id,
        user["balance"],
        user["bushes"],
        user["normal_snus"],
        user["rotten_snus"],
    )
    await message.answer(
        f"💵 Ты продал {normal_count} шт. нормального снюса за {earned} руб.!\n"
        f"Текущий баланс: {user['balance']} руб."
    )
  else:
    await message.answer("❌ У тебя нет нормального снюса для продажи!")


# ==================== ФОНОВЫЙ РОСТ (каждые 15 мин) ====================
async def grow_snus_loop():
  while True:
    # 900 секунд = 15 минут
    await asyncio.sleep(900)

    cursor.execute(
        "SELECT user_id, bushes, normal_snus, rotten_snus FROM users WHERE"
        " bushes > 0"
    )
    all_users = cursor.fetchall()

    for row in all_users:
      user_id, bushes, normal, rotten = row
      # С каждого куста растет до 4 снюсов. Шанс 25% (1 из 4), что вырастет гнилой
      for _ in range(bushes * 4):
        is_rotten = random.randint(1, 4) == 1
        if is_rotten:
          rotten += 1
        else:
          normal += 1

      cursor.execute(
          "UPDATE users SET normal_snus = ?, rotten_snus = ? WHERE user_id ="
          " ?",
          (normal, rotten, user_id),
      )
      conn.commit()
    logging.info("Урожай снюса обновился у всех игроков!")


# ==================== FLASK-СЕРВЕР (Для Render.com) ====================
app = Flask(__name__)


@app.route("/")
def index():
  return "Snus Farm Bot is running 24/7!"


def run_flask():
  # Сервер слушает порт 8080
  app.run(host="0.0.0.0", port=8080)


# ==================== ЗАПУСК ====================
async def main():
  # Запускаем Flask в фоновом потоке
  flask_thread = threading.Thread(target=run_flask, daemon=True)
  flask_thread.start()

  # Запускаем фоновый рост снюса
  asyncio.create_task(grow_snus_loop())

  # Запускаем самого Telegram-бота
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
