import asyncio
import logging
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

# =========================
# НАСТРОЙКИ
# =========================

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = "@pbtestboto"

# =========================
# ЛОГИ
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

# =========================
# BOT
# =========================

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в переменных FadeHost")

bot = Bot(TOKEN)
dp = Dispatcher()

# =========================
# DATABASE
# =========================

db = sqlite3.connect(
    "battle.db",
    check_same_thread=False
)

db.row_factory = sqlite3.Row


def init_db():
    db.execute("""
        CREATE TABLE IF NOT EXISTS waiting (
            user_id INTEGER PRIMARY KEY,
            photo_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    db.commit()


init_db()

# =========================
# START
# =========================


@dp.message(Command("start"))
async def start_handler(message: Message):

    print(
        f"START: {message.from_user.id}",
        flush=True
    )

    await message.answer(
        "📸 <b>ФОТОБАТЛ</b>\n\n"
        "Отправь фотографию.\n"
        "Если ты первый — подождём второго участника.\n"
        "Если второй уже ждёт — батл создастся автоматически.\n\n"
        "/cancel — выйти из очереди.",
        parse_mode="HTML"
    )


# =========================
# CANCEL
# =========================


@dp.message(Command("cancel"))
async def cancel_handler(message: Message):

    user_id = message.from_user.id

    result = db.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (user_id,)
    )

    db.commit()

    if result.rowcount:
        await message.answer(
            "❌ Ты вышел из очереди."
        )
    else:
        await message.answer(
            "ℹ️ Ты сейчас не находишься в очереди."
        )


# =========================
# PHOTO
# =========================


@dp.message(F.photo)
async def photo_handler(message: Message):

    user_id = message.from_user.id

    # Берём самое большое качество фотографии
    photo_id = message.photo[-1].file_id

    print(
        f"PHOTO RECEIVED: user={user_id}",
        flush=True
    )

    print(
        f"PHOTO ID: {photo_id}",
        flush=True
    )

    # =========================
    # ПРОВЕРЯЕМ, НЕ В ОЧЕРЕДИ ЛИ
    # =========================

    already_waiting = db.execute(
        """
        SELECT user_id
        FROM waiting
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    if already_waiting:

        await message.answer(
            "⏳ Ты уже ждёшь второго участника.\n\n"
            "Если хочешь выйти — используй /cancel."
        )

        return

    # =========================
    # ИЩЕМ СОПЕРНИКА
    # =========================

    opponent = db.execute(
        """
        SELECT user_id, photo_id
        FROM waiting
        WHERE user_id != ?
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (user_id,)
    ).fetchone()

    # =========================
    # СОПЕРНИКА НЕТ
    # =========================

    if not opponent:

        db.execute(
            """
            INSERT INTO waiting(
                user_id,
                photo_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                photo_id,
                datetime.now().isoformat()
            )
        )

        db.commit()

        logger.info(
            "USER ADDED TO QUEUE | user=%s",
            user_id
        )

        await message.answer(
            "⏳ <b>Фото принято!</b>\n\n"
            "Ты первый участник.\n"
            "Ждём второго человека.",
            parse_mode="HTML"
        )

        return

    # =========================
    # ВТОРОЙ УЧАСТНИК НАЙДЕН
    # =========================

    opponent_id = opponent["user_id"]
    opponent_photo = opponent["photo_id"]

    logger.info(
        "SECOND USER FOUND | user1=%s | user2=%s",
        opponent_id,
        user_id
    )

    # Удаляем первого из очереди
    db.execute(
        """
        DELETE FROM waiting
        WHERE user_id = ?
        """,
        (opponent_id,)
    )

    db.commit()

    # =========================
    # ОТПРАВЛЯЕМ ФОТО 1
    # =========================

    try:

        sent_photo_1 = await bot.send_photo(
            chat_id=CHANNEL,
            photo=opponent_photo,
            caption=(
                "📸 <b>УЧАСТНИК 1</b>"
            ),
            parse_mode="HTML"
        )

        logger.info(
            "PHOTO 1 SENT | message_id=%s",
            sent_photo_1.message_id
        )

    except Exception as error:

        logger.exception(
            "ERROR SENDING PHOTO 1"
        )

        # Возвращаем первого пользователя обратно в очередь
        db.execute(
            """
            INSERT OR REPLACE INTO waiting(
                user_id,
                photo_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                opponent_id,
                opponent_photo,
                datetime.now().isoformat()
            )
        )

        db.commit()

        await message.answer(
            "❌ Не удалось отправить батл в канал.\n\n"
            "Проверь, что бот является администратором "
            "канала и имеет право публиковать сообщения."
        )

        return

    # =========================
    # ОТПРАВЛЯЕМ ФОТО 2
    # =========================

    try:

        sent_photo_2 = await bot.send_photo(
            chat_id=CHANNEL,
            photo=photo_id,
            caption=(
                "📸 <b>УЧАСТНИК 2</b>"
            ),
            parse_mode="HTML"
        )

        logger.info(
            "PHOTO 2 SENT | message_id=%s",
            sent_photo_2.message_id
        )

    except Exception as error:

        logger.exception(
            "ERROR SENDING PHOTO 2"
        )

        await message.answer(
            "❌ Первое фото отправилось, "
            "но второе не удалось отправить."
        )

        return

    # =========================
    # СООБЩЕНИЕ О БАТЛЕ
    # =========================

    try:

        await bot.send_message(
            chat_id=CHANNEL,
            text=(
                "📸 <b>ФОТОБАТЛ</b>\n\n"
                "🔥 Участник 1\n"
                "❤️ Участник 2\n\n"
                "Голосование скоро будет добавлено."
            ),
            parse_mode="HTML"
        )

        logger.info(
            "BATTLE PUBLISHED | user1=%s | user2=%s",
            opponent_id,
            user_id
        )

    except Exception:

        logger.exception(
            "ERROR SENDING BATTLE MESSAGE"
        )

    # =========================
    # ОТВЕТ УЧАСТНИКАМ
    # =========================

    await message.answer(
        "🔥 <b>Батл создан!</b>\n\n"
        "Твоя фотография — <b>участник 2</b>.",
        parse_mode="HTML"
    )

    try:

        await bot.send_message(
            chat_id=opponent_id,
            text=(
                "🔥 <b>Батл создан!</b>\n\n"
                "Твоя фотография — <b>участник 1</b>."
            ),
            parse_mode="HTML"
        )

    except Exception as error:

        logger.warning(
            "Не удалось уведомить первого участника: %s",
            error
        )


# =========================
# ЛЮБОЕ ДРУГОЕ СООБЩЕНИЕ
# =========================


@dp.message()
async def other_message_handler(message: Message):

    print(
        f"MESSAGE RECEIVED: type={message.content_type}",
        flush=True
    )

    # Не отвечаем на всё подряд,
    # чтобы бот не спамил пользователю.


# =========================
# START BOT
# =========================


async def main():

    logger.info(
        "=============================="
    )

    logger.info(
        "PHOTO BATTLE BOT STARTING"
    )

    logger.info(
        "CHANNEL = %s",
        CHANNEL
    )

    logger.info(
        "TOKEN EXISTS = %s",
        bool(TOKEN)
    )

    logger.info(
        "=============================="
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
