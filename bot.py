import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message


TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = "@pbtestboto"


if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден в переменной окружения BOT_TOKEN"
    )


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# =========================================================
# BOT
# =========================================================

bot = Bot(token=TOKEN)
dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    "battle.db",
    check_same_thread=False,
)

db.row_factory = sqlite3.Row


db.execute("""
CREATE TABLE IF NOT EXISTS waiting (
    user_id INTEGER PRIMARY KEY,
    photo_id TEXT NOT NULL,
    created_at TEXT NOT NULL
)
""")


db.execute("""
CREATE TABLE IF NOT EXISTS battles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    user1_id INTEGER NOT NULL,
    user1_photo TEXT NOT NULL,

    user2_id INTEGER NOT NULL,
    user2_photo TEXT NOT NULL,

    channel_message_1 INTEGER,
    channel_message_2 INTEGER,
    channel_message_battle INTEGER,

    created_at TEXT NOT NULL
)
""")


db.commit()


# Защищает SQLite от одновременных операций
db_lock = asyncio.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# =========================================================
# QUEUE
# =========================================================

async def add_to_queue(
    user_id: int,
    photo_id: str,
):
    """
    Добавляет пользователя в очередь.

    Возвращает:
        True  — добавили
        False — пользователь уже в очереди
    """

    async with db_lock:

        exists = db.execute(
            """
            SELECT 1
            FROM waiting
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        if exists:
            return False

        db.execute(
            """
            INSERT INTO waiting (
                user_id,
                photo_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                photo_id,
                now_iso(),
            ),
        )

        db.commit()

        return True


async def find_opponent(
    user_id: int,
):
    """
    Находит самого старого соперника.

    Одновременно удаляет из очереди:
        - найденного соперника
        - текущего пользователя

    Это важно: после формирования батла никто
    не должен оставаться в waiting.
    """

    async with db_lock:

        opponent = db.execute(
            """
            SELECT
                user_id,
                photo_id
            FROM waiting
            WHERE user_id != ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if opponent is None:
            return None

        db.execute(
            """
            DELETE FROM waiting
            WHERE user_id IN (?, ?)
            """,
            (
                opponent["user_id"],
                user_id,
            ),
        )

        db.commit()

        return opponent


async def put_back_in_queue(
    user_id: int,
    photo_id: str,
):
    """
    Возвращает пользователя в очередь,
    если публикация батла не удалась.
    """

    async with db_lock:

        exists = db.execute(
            """
            SELECT 1
            FROM waiting
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        if exists:
            return

        db.execute(
            """
            INSERT INTO waiting (
                user_id,
                photo_id,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                photo_id,
                now_iso(),
            ),
        )

        db.commit()


# =========================================================
# /START
# =========================================================

@dp.message(Command("start"))
async def start_handler(message: Message):

    user_id = message.from_user.id

    logger.info(
        "START | user=%s",
        user_id,
    )

    await message.answer(
        "✅ <b>Бот работает.</b>\n\n"
        "📸 Отправь фотографию, чтобы встать "
        "в очередь на фотобатл.\n\n"
        "❌ /cancel — выйти из очереди.",
        parse_mode="HTML",
    )


# =========================================================
# /CANCEL
# =========================================================

@dp.message(Command("cancel"))
async def cancel_handler(message: Message):

    user_id = message.from_user.id

    async with db_lock:

        cursor = db.execute(
            """
            DELETE FROM waiting
            WHERE user_id = ?
            """,
            (user_id,),
        )

        db.commit()

    if cursor.rowcount:

        logger.info(
            "QUEUE REMOVE | user=%s",
            user_id,
        )

        await message.answer(
            "❌ Ты вышел из очереди."
        )

    else:

        await message.answer(
            "ℹ️ Тебя нет в очереди."
        )


# =========================================================
# ALL MESSAGES
# =========================================================

@dp.message()
async def photo_handler(message: Message):

    user_id = message.from_user.id

    logger.info(
        "MESSAGE | user=%s | type=%s | has_photo=%s",
        user_id,
        message.content_type,
        bool(message.photo),
    )

    # =====================================================
    # НЕ ФОТО
    # =====================================================

    if not message.photo:

        await message.answer(
            "📸 Я принимаю только фотографии.\n\n"
            "Отправь фото обычным сообщением."
        )

        return

    # =====================================================
    # ПОЛУЧАЕМ PHOTO ID
    # =====================================================

    photo_id = message.photo[-1].file_id

    logger.info(
        "PHOTO RECEIVED | user=%s | file_id=%s",
        user_id,
        photo_id,
    )

    # =====================================================
    # ДОБАВЛЯЕМ В ОЧЕРЕДЬ
    # =====================================================

    added = await add_to_queue(
        user_id=user_id,
        photo_id=photo_id,
    )

    if not added:

        await message.answer(
            "⏳ Ты уже находишься в очереди.\n\n"
            "Если хочешь выйти — используй /cancel."
        )

        logger.info(
            "QUEUE ALREADY EXISTS | user=%s",
            user_id,
        )

        return

    logger.info(
        "QUEUE ADD | user=%s",
        user_id,
    )

    # =====================================================
    # ИЩЕМ СОПЕРНИКА
    # =====================================================

    opponent = await find_opponent(
        user_id=user_id,
    )

    # =====================================================
    # СОПЕРНИКА НЕТ
    # =====================================================

    if opponent is None:

        await message.answer(
            "✅ <b>Фото принято!</b>\n\n"
            "⏳ Ты первый участник.\n"
            "Ждём соперника.",
            parse_mode="HTML",
        )

        logger.info(
            "WAITING FOR OPPONENT | user=%s",
            user_id,
        )

        return

    # =====================================================
    # СОПЕРНИК НАЙДЕН
    # =====================================================

    opponent_id = opponent["user_id"]
    opponent_photo = opponent["photo_id"]

    logger.info(
        "BATTLE FOUND | user1=%s | user2=%s",
        opponent_id,
        user_id,
    )

    # =====================================================
    # ПУБЛИКАЦИЯ БАТЛА
    # =====================================================

    msg1 = None
    msg2 = None
    battle_msg = None

    try:

        # -------------------------------------------------
        # ФОТО УЧАСТНИКА 1
        # -------------------------------------------------

        msg1 = await bot.send_photo(
            chat_id=CHANNEL,
            photo=opponent_photo,
            caption="📸 <b>УЧАСТНИК 1</b>",
            parse_mode="HTML",
        )

        logger.info(
            "CHANNEL PHOTO 1 OK | message_id=%s",
            msg1.message_id,
        )

        # -------------------------------------------------
        # ФОТО УЧАСТНИКА 2
        # -------------------------------------------------

        msg2 = await bot.send_photo(
            chat_id=CHANNEL,
            photo=photo_id,
            caption="📸 <b>УЧАСТНИК 2</b>",
            parse_mode="HTML",
        )

        logger.info(
            "CHANNEL PHOTO 2 OK | message_id=%s",
            msg2.message_id,
        )

        # -------------------------------------------------
        # СООБЩЕНИЕ БАТЛА
        # -------------------------------------------------

        battle_msg = await bot.send_message(
            chat_id=CHANNEL,
            text=(
                "📸 <b>ФОТОБАТЛ</b>\n\n"
                "1️⃣ Участник 1\n"
                "2️⃣ Участник 2\n\n"
                "🔥 Голосуй за понравившееся фото!"
            ),
            parse_mode="HTML",
        )

        logger.info(
            "CHANNEL BATTLE OK | message_id=%s",
            battle_msg.message_id,
        )

    except Exception:

        logger.exception(
            "BATTLE PUBLISH ERROR | user1=%s | user2=%s",
            opponent_id,
            user_id,
        )

        # =================================================
        # ЕСЛИ ПУБЛИКАЦИЯ НЕ УДАЛАСЬ —
        # ВОЗВРАЩАЕМ ОБОИХ В ОЧЕРЕДЬ
        # =================================================

        await put_back_in_queue(
            user_id=opponent_id,
            photo_id=opponent_photo,
        )

        await put_back_in_queue(
            user_id=user_id,
            photo_id=photo_id,
        )

        await message.answer(
            "❌ Не удалось опубликовать батл в канал.\n\n"
            "Фото возвращены в очередь."
        )

        return

    # =====================================================
    # СОХРАНЯЕМ БАТЛ
    # =====================================================

    async with db_lock:

        db.execute(
            """
            INSERT INTO battles (
                user1_id,
                user1_photo,
                user2_id,
                user2_photo,
                channel_message_1,
                channel_message_2,
                channel_message_battle,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opponent_id,
                opponent_photo,

                user_id,
                photo_id,

                msg1.message_id,
                msg2.message_id,
                battle_msg.message_id,

                now_iso(),
            ),
        )

        db.commit()

    logger.info(
        "BATTLE SAVED | user1=%s | user2=%s",
        opponent_id,
        user_id,
    )

    # =====================================================
    # ОТВЕТ ВТОРОМУ УЧАСТНИКУ
    # =====================================================

    await message.answer(
        "🔥 <b>Батл создан!</b>\n\n"
        "Ты — <b>участник 2</b>.",
        parse_mode="HTML",
    )

    # =====================================================
    # УВЕДОМЛЕНИЕ ПЕРВОМУ
    # =====================================================

    try:

        await bot.send_message(
            chat_id=opponent_id,
            text=(
                "🔥 <b>Батл создан!</b>\n\n"
                "Ты — <b>участник 1</b>."
            ),
            parse_mode="HTML",
        )

    except Exception:

        logger.warning(
            "USER NOTIFICATION ERROR | user=%s",
            opponent_id,
            exc_info=True,
        )


# =========================================================
# MAIN
# =========================================================

async def main():

    logger.info("==============================")
    logger.info("BOT STARTING")
    logger.info("CHANNEL: %s", CHANNEL)
    logger.info("==============================")

    # Убираем webhook.
    # Старые pending updates НЕ удаляем.
    await bot.delete_webhook(
        drop_pending_updates=False
    )

    # =====================================================
    # ПРОВЕРКА КАНАЛА ПЕРЕД ЗАПУСКОМ
    # =====================================================

    try:

        chat = await bot.get_chat(CHANNEL)

        logger.info(
            "CHANNEL CHECK OK | id=%s | title=%s",
            chat.id,
            chat.title,
        )

    except Exception:

        logger.exception(
            "CHANNEL CHECK FAILED.\n"
            "Проверь CHANNEL и убедись, что бот добавлен "
            "в канал и имеет права администратора."
        )

        raise

    # =====================================================
    # POLLING
    # =====================================================

    try:

        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )

    finally:

        await bot.session.close()
        db.close()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
