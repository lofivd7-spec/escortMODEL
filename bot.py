import os
import sqlite3
import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
)
from aiogram.filters import CommandStart, Command


BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = "@pbtestboto"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB = "battle.db"

# ================= НАСТРОЙКИ =================

DEFAULT_PRIZE = "1000₽"
DEFAULT_RESULT_TIME = "22:00"

# ВАЖНО: сюда впиши свой Telegram ID
ADMIN_ID = 123456789


# ================= DATABASE =================

def db():
    return sqlite3.connect(DB)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS waiting (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            photo_id TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1 INTEGER NOT NULL,
            user2 INTEGER NOT NULL,
            photo1 TEXT NOT NULL,
            photo2 TEXT NOT NULL,
            message_id INTEGER,
            votes1 INTEGER DEFAULT 0,
            votes2 INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            battle_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            choice INTEGER NOT NULL,
            PRIMARY KEY (battle_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Создаём настройки по умолчанию
    cur.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        ("prize", DEFAULT_PRIZE)
    )

    cur.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        ("result_time", DEFAULT_RESULT_TIME)
    )

    con.commit()
    con.close()


def get_setting(key):
    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    result = cur.fetchone()
    con.close()

    if result:
        return result[0]

    return None


def set_setting(key, value):
    con = db()
    cur = con.cursor()

    cur.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, value)
    )

    con.commit()
    con.close()


# ================= KEYBOARD =================

def vote_keyboard(battle_id, votes1=0, votes2=0):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔥 {votes1}",
                    callback_data=f"vote:{battle_id}:1"
                ),
                InlineKeyboardButton(
                    text=f"❤️ {votes2}",
                    callback_data=f"vote:{battle_id}:2"
                )
            ]
        ]
    )


def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Изменить приз",
                    callback_data="admin_prize"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🕐 Изменить время",
                    callback_data="admin_time"
                )
            ]
        ]
    )


# ================= ADMIN =================

def is_admin(user_id):
    return user_id == ADMIN_ID


@dp.message(Command("admin"))
async def admin_panel(message: Message):

    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    prize = get_setting("prize")
    result_time = get_setting("result_time")

    await message.answer(
        "👑 АДМИН-ПАНЕЛЬ\n\n"
        f"💰 Приз: {prize}\n"
        f"🕐 Окончание: {result_time}\n\n"
        "Выбери настройку:",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(F.data == "admin_prize")
async def admin_prize(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return

    await callback.message.answer(
        "💰 Введи новый приз.\n\n"
        "Например:\n"
        "5000₽"
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_time")
async def admin_time(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return

    await callback.message.answer(
        "🕐 Введи новое время окончания.\n\n"
        "Формат:\n"
        "ЧЧ:ММ\n\n"
        "Например:\n"
        "23:30"
    )

    await callback.answer()


@dp.message()
async def admin_text_handler(message: Message):

    if not is_admin(message.from_user.id):
        return

    text = message.text.strip() if message.text else ""

    # Проверяем время
    try:
        datetime.strptime(text, "%H:%M")

        set_setting("result_time", text)

        await message.answer(
            f"✅ Время окончания изменено на {text}"
        )

        return

    except ValueError:
        pass

    # Если это не время — можно считать призом,
    # но команды и обычные сообщения не трогаем
    if text and not text.startswith("/"):
        set_setting("prize", text)

        await message.answer(
            f"✅ Приз изменён на {text}"
        )


# ================= START =================

@dp.message(CommandStart())
async def start(message: Message):

    await message.answer(
        "📸 Фотобатлы\n\n"
        "Отправь мне свою фотографию.\n"
        "Я поставлю её в очередь и дождусь второго участника."
    )


# ================= CANCEL =================

@dp.message(Command("cancel"))
async def cancel(message: Message):

    con = db()
    cur = con.cursor()

    cur.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (message.from_user.id,)
    )

    deleted = cur.rowcount

    con.commit()
    con.close()

    if deleted:
        await message.answer(
            "❌ Твоя фотография удалена из очереди."
        )
    else:
        await message.answer(
            "У тебя сейчас нет фотографии в очереди."
        )


# ================= PHOTO =================

@dp.message(F.photo)
async def photo_received(message: Message):

    user_id = message.from_user.id
    username = message.from_user.username or ""

    photo_id = message.photo[-1].file_id

    con = db()
    cur = con.cursor()

    cur.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (user_id,)
    )

    cur.execute(
        "SELECT user_id, username, photo_id FROM waiting LIMIT 1"
    )

    opponent = cur.fetchone()

    if not opponent:

        cur.execute(
            """
            INSERT INTO waiting
            (user_id, username, photo_id)
            VALUES (?, ?, ?)
            """,
            (user_id, username, photo_id)
        )

        con.commit()
        con.close()

        await message.answer(
            "✅ Фото принято!\n\n"
            "Ты участник №1.\n"
            "Теперь ждём второго участника."
        )

        return

    user1, username1, photo1 = opponent

    if user1 == user_id:

        con.close()

        await message.answer(
            "❌ Нельзя участвовать самому с собой."
        )

        return

    cur.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (user1,)
    )

    cur.execute(
        """
        INSERT INTO battles
        (user1, user2, photo1, photo2)
        VALUES (?, ?, ?, ?)
        """,
        (user1, user_id, photo1, photo_id)
    )

    battle_id = cur.lastrowid

    con.commit()
    con.close()

    prize = get_setting("prize")
    result_time = get_setting("result_time")

    await message.answer(
        f"🔥 Батл сформирован!\n\n"
        f"Ты участник №2.\n"
        f"Батл №{battle_id} опубликован в канале."
    )

    media = [
        InputMediaPhoto(media=photo1),
        InputMediaPhoto(media=photo_id)
    ]

    await bot.send_media_group(
        chat_id=CHANNEL,
        media=media
    )

    text = (
        f"📸 ФОТОБАТЛ №{battle_id}\n\n"
        f"1 — 🔥\n"
        f"2 — ❤️\n\n"
        f"Итоги в {result_time}\n"
        f"Приз — {prize}"
    )

    sent = await bot.send_message(
        chat_id=CHANNEL,
        text=text,
        reply_markup=vote_keyboard(battle_id)
    )

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        UPDATE battles
        SET message_id = ?
        WHERE id = ?
        """,
        (sent.message_id, battle_id)
    )

    con.commit()
    con.close()


# ================= VOTE =================

@dp.callback_query(F.data.startswith("vote:"))
async def vote(callback: CallbackQuery):

    _, battle_id, choice = callback.data.split(":")

    battle_id = int(battle_id)
    choice = int(choice)

    user_id = callback.from_user.id

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT votes1, votes2, active, message_id
        FROM battles
        WHERE id = ?
        """,
        (battle_id,)
    )

    battle = cur.fetchone()

    if not battle:

        con.close()

        await callback.answer(
            "Батл не найден.",
            show_alert=True
        )

        return

    votes1, votes2, active, message_id = battle

    if not active:

        con.close()

        await callback.answer(
            "Голосование уже завершено.",
            show_alert=True
        )

        return

    cur.execute(
        """
        SELECT choice
        FROM votes
        WHERE battle_id = ? AND user_id = ?
        """,
        (battle_id, user_id)
    )

    old_vote = cur.fetchone()

    if old_vote:

        old_choice = old_vote[0]

        if old_choice == choice:

            con.close()

            await callback.answer(
                "Ты уже проголосовал за этот вариант."
            )

            return

        if old_choice == 1:
            votes1 -= 1
        else:
            votes2 -= 1

        if choice == 1:
            votes1 += 1
        else:
            votes2 += 1

        cur.execute(
            """
            UPDATE votes
            SET choice = ?
            WHERE battle_id = ? AND user_id = ?
            """,
            (choice, battle_id, user_id)
        )

    else:

        if choice == 1:
            votes1 += 1
        else:
            votes2 += 1

        cur.execute(
            """
            INSERT INTO votes
            (battle_id, user_id, choice)
            VALUES (?, ?, ?)
            """,
            (battle_id, user_id, choice)
        )

    cur.execute(
        """
        UPDATE battles
        SET votes1 = ?, votes2 = ?
        WHERE id = ?
        """,
        (votes1, votes2, battle_id)
    )

    con.commit()
    con.close()

    await bot.edit_message_reply_markup(
        chat_id=CHANNEL,
        message_id=message_id,
        reply_markup=vote_keyboard(
            battle_id,
            votes1,
            votes2
        )
    )

    await callback.answer("Голос засчитан! 👍")


# ================= MAIN =================

async def main():

    init_db()

    print("Бот запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
