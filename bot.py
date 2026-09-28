import os
import sqlite3
import asyncio

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

# Настройки батла
PRIZE = "1000₽"
RESULT_TIME = "22:00"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB = "battle.db"


# ---------------- DATABASE ----------------

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

    con.commit()
    con.close()


# ---------------- KEYBOARD ----------------

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


# ---------------- START ----------------

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "📸 Фотобатлы\n\n"
        "Отправь мне свою фотографию.\n"
        "Я поставлю её в очередь и дождусь второго участника."
    )


# ---------------- CANCEL ----------------

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
        await message.answer("❌ Твоя фотография удалена из очереди.")
    else:
        await message.answer("У тебя сейчас нет фотографии в очереди.")


# ---------------- PHOTO ----------------

@dp.message(F.photo)
async def photo_received(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""

    # Берём фотографию максимального качества
    photo_id = message.photo[-1].file_id

    con = db()
    cur = con.cursor()

    # Если пользователь уже стоит в очереди — заменяем его фото
    cur.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (user_id,)
    )

    # Проверяем, есть ли уже ожидающий участник
    cur.execute(
        "SELECT user_id, username, photo_id FROM waiting LIMIT 1"
    )

    opponent = cur.fetchone()

    if not opponent:
        cur.execute(
            """
            INSERT INTO waiting (user_id, username, photo_id)
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

    # Второй участник найден
    user1, username1, photo1 = opponent

    # Не даём одному пользователю стать обоими участниками
    if user1 == user_id:
        con.close()
        await message.answer("❌ Нельзя участвовать самому с собой.")
        return

    # Убираем первого из очереди
    cur.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (user1,)
    )

    # Создаём батл
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

    await message.answer(
        f"🔥 Батл сформирован!\n\n"
        f"Ты участник №2.\n"
        f"Батл №{battle_id} опубликован в канале."
    )

    # Публикуем фотографии
    media = [
        InputMediaPhoto(
            media=photo1
        ),
        InputMediaPhoto(
            media=photo_id
        )
    ]

    await bot.send_media_group(
        chat_id=CHANNEL,
        media=media
    )

    # Отдельное сообщение с голосованием
    text = (
        f"📸 ФОТОБАТЛ №{battle_id}\n\n"
        f"1 — 🔥\n"
        f"2 — ❤️\n\n"
        f"Итоги в {RESULT_TIME}\n"
        f"Приз — {PRIZE}"
    )

    sent = await bot.send_message(
        chat_id=CHANNEL,
        text=text,
        reply_markup=vote_keyboard(battle_id)
    )

    # Запоминаем ID сообщения с кнопками
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


# ---------------- VOTE ----------------

@dp.callback_query(F.data.startswith("vote:"))
async def vote(callback: CallbackQuery):
    _, battle_id, choice = callback.data.split(":")

    battle_id = int(battle_id)
    choice = int(choice)
    user_id = callback.from_user.id

    con = db()
    cur = con.cursor()

    # Проверяем батл
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
        await callback.answer("Батл не найден.", show_alert=True)
        return

    votes1, votes2, active, message_id = battle

    if not active:
        con.close()
        await callback.answer("Голосование уже завершено.", show_alert=True)
        return

    # Проверяем предыдущий голос
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
            await callback.answer("Ты уже проголосовал за этот вариант.")
            return

        # Переключаем голос
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
        # Новый голос
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

    # Обновляем цифры на кнопках
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


# ---------------- MAIN ----------------

async def main():
    init_db()

    print("Бот запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
