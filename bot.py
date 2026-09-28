import asyncio
import logging
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = "@pbtestboto"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

bot = Bot(TOKEN)
dp = Dispatcher()

db = sqlite3.connect(
    "battle.db",
    check_same_thread=False
)

db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS waiting (
    user_id INTEGER PRIMARY KEY,
    photo_id TEXT NOT NULL,
    created_at TEXT NOT NULL
)
""")

db.commit()


@dp.message(Command("start"))
async def start_handler(message: Message):
    print(
        f"START | user={message.from_user.id}",
        flush=True
    )

    await message.answer(
        "✅ Бот работает.\n\n"
        "📸 Отправь фотографию."
    )


@dp.message(Command("cancel"))
async def cancel_handler(message: Message):
    user_id = message.from_user.id

    db.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (user_id,)
    )

    db.commit()

    await message.answer(
        "❌ Ты вышел из очереди."
    )


@dp.message()
async def message_handler(message: Message):

    print(
        f"MESSAGE | user={message.from_user.id} "
        f"type={message.content_type} "
        f"has_photo={bool(message.photo)}",
        flush=True
    )

    # ==========================================
    # ФОТО
    # ==========================================

    if message.photo:

        user_id = message.from_user.id
        photo_id = message.photo[-1].file_id

        print(
            f"PHOTO FOUND | user={user_id} | id={photo_id}",
            flush=True
        )

        # ------------------------------------------
        # Проверяем очередь этого пользователя
        # ------------------------------------------

        exists = db.execute(
            """
            SELECT user_id
            FROM waiting
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if exists:

            await message.answer(
                "⏳ Ты уже находишься в очереди.\n\n"
                "Используй /cancel, если хочешь выйти."
            )

            return

        # ------------------------------------------
        # Ищем первого участника
        # ------------------------------------------

        opponent = db.execute(
            """
            SELECT user_id, photo_id
            FROM waiting
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()

        # ==========================================
        # ПЕРВЫЙ УЧАСТНИК
        # ==========================================

        if opponent is None:

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

            print(
                f"QUEUE ADD | user={user_id}",
                flush=True
            )

            await message.answer(
                "⏳ <b>Фото принято!</b>\n\n"
                "Ты первый участник.\n"
                "Ждём второго.",
                parse_mode="HTML"
            )

            return

        # ==========================================
        # ВТОРОЙ УЧАСТНИК
        # ==========================================

        opponent_id = opponent["user_id"]
        opponent_photo = opponent["photo_id"]

        print(
            f"BATTLE | user1={opponent_id} "
            f"user2={user_id}",
            flush=True
        )

        # Удаляем из очереди
        db.execute(
            "DELETE FROM waiting WHERE user_id = ?",
            (opponent_id,)
        )

        db.commit()

        # ==========================================
        # ОТПРАВЛЯЕМ ПЕРВОЕ ФОТО
        # ==========================================

        try:

            await bot.send_photo(
                chat_id=CHANNEL,
                photo=opponent_photo,
                caption="📸 <b>УЧАСТНИК 1</b>",
                parse_mode="HTML"
            )

            print(
                "CHANNEL PHOTO 1 OK",
                flush=True
            )

        except Exception as e:

            logger.exception(
                "CHANNEL PHOTO 1 ERROR"
            )

            await message.answer(
                "❌ Не удалось отправить первое фото в канал."
            )

            return

        # ==========================================
        # ОТПРАВЛЯЕМ ВТОРОЕ ФОТО
        # ==========================================

        try:

            await bot.send_photo(
                chat_id=CHANNEL,
                photo=photo_id,
                caption="📸 <b>УЧАСТНИК 2</b>",
                parse_mode="HTML"
            )

            print(
                "CHANNEL PHOTO 2 OK",
                flush=True
            )

        except Exception as e:

            logger.exception(
                "CHANNEL PHOTO 2 ERROR"
            )

            await message.answer(
                "❌ Не удалось отправить второе фото в канал."
            )

            return

        # ==========================================
        # СООБЩЕНИЕ БАТЛА
        # ==========================================

        await bot.send_message(
            chat_id=CHANNEL,
            text=(
                "📸 <b>ФОТОБАТЛ</b>\n\n"
                "🔥 Участник 1\n"
                "❤️ Участник 2"
            ),
            parse_mode="HTML"
        )

        # ==========================================
        # ОТВЕТ ВТОРОМУ
        # ==========================================

        await message.answer(
            "🔥 <b>Батл создан!</b>\n\n"
            "Ты — участник 2.",
            parse_mode="HTML"
        )

        # ==========================================
        # УВЕДОМЛЯЕМ ПЕРВОГО
        # ==========================================

        try:

            await bot.send_message(
                chat_id=opponent_id,
                text=(
                    "🔥 <b>Батл создан!</b>\n\n"
                    "Ты — участник 1."
                ),
                parse_mode="HTML"
            )

        except Exception as e:

            logger.warning(
                "USER NOTIFICATION ERROR: %s",
                e
            )

        return

    # ==========================================
    # НЕ ФОТО
    # ==========================================

    print(
        f"NOT PHOTO | type={message.content_type}",
        flush=True
    )


async def main():

    print(
        "==============================",
        flush=True
    )

    print(
        "BOT STARTING",
        flush=True
    )

    print(
        f"TOKEN EXISTS: {bool(TOKEN)}",
        flush=True
    )

    print(
        f"CHANNEL: {CHANNEL}",
        flush=True
    )

    print(
        "==============================",
        flush=True
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
