import asyncio
import logging
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = "@pbtestboto"
ADMIN_ID = 8641624229

DEFAULT_PRIZE = "1000₽"
DEFAULT_RESULT_TIME = "22:00"
BOOST_PRICE_PER_VOTE = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db = sqlite3.connect("battle.db", check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")


def get_setting(key: str, default=None):
    row = db.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    db.execute(
        """
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value))
    )
    db.commit()


def init_db():
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS waiting (
            user_id INTEGER PRIMARY KEY,
            photo_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER NOT NULL,
            user1_photo TEXT NOT NULL,
            user2_id INTEGER NOT NULL,
            user2_photo TEXT NOT NULL,
            channel_photo1_message_id INTEGER,
            channel_photo2_message_id INTEGER,
            vote_message_id INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS votes (
            battle_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            participant INTEGER NOT NULL,
            PRIMARY KEY (battle_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS boosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            participant INTEGER NOT NULL,
            votes INTEGER NOT NULL,
            stars INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    if get_setting("prize") is None:
        set_setting("prize", DEFAULT_PRIZE)

    if get_setting("result_time") is None:
        set_setting("result_time", DEFAULT_RESULT_TIME)

    db.commit()


init_db()

admin_mode = {}
boost_pending = {}


def vote_keyboard(battle_id: int, votes1: int, votes2: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔥 {votes1}",
                    callback_data=f"vote_{battle_id}_1"
                ),
                InlineKeyboardButton(
                    text=f"❤️ {votes2}",
                    callback_data=f"vote_{battle_id}_2"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="БУСТ РЕАКЦИЙ ⚡️",
                    callback_data=f"boost_{battle_id}"
                )
            ],
        ]
    )


def participant_keyboard(battle_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔥 УЧАСТНИК 1",
                    callback_data=f"boostparticipant_{battle_id}_1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❤️ УЧАСТНИК 2",
                    callback_data=f"boostparticipant_{battle_id}_2"
                )
            ],
        ]
    )


def admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🏆 Приз: {get_setting('prize')}",
                    callback_data="admin_prize"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"⏰ Время: {get_setting('result_time')}",
                    callback_data="admin_time"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin_stats"
                )
            ],
        ]
    )


def get_totals(battle_id: int):
    totals = {1: 0, 2: 0}

    rows = db.execute(
        """
        SELECT participant, COUNT(*) AS cnt
        FROM votes
        WHERE battle_id = ?
        GROUP BY participant
        """,
        (battle_id,)
    ).fetchall()

    for row in rows:
        totals[row["participant"]] += row["cnt"]

    rows = db.execute(
        """
        SELECT participant, COALESCE(SUM(votes), 0) AS cnt
        FROM boosts
        WHERE battle_id = ?
        GROUP BY participant
        """,
        (battle_id,)
    ).fetchall()

    for row in rows:
        totals[row["participant"]] += row["cnt"]

    return totals


async def update_vote_buttons(battle_id: int):
    battle = db.execute(
        "SELECT vote_message_id FROM battles WHERE id = ?",
        (battle_id,)
    ).fetchone()

    if not battle or not battle["vote_message_id"]:
        return

    totals = get_totals(battle_id)

    try:
        await bot.edit_message_reply_markup(
            chat_id=CHANNEL,
            message_id=battle["vote_message_id"],
            reply_markup=vote_keyboard(
                battle_id,
                totals[1],
                totals[2]
            )
        )
    except Exception as e:
        logger.warning(
            "Could not update vote buttons for battle %s: %s",
            battle_id,
            e
        )


@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "📸 <b>ФОТОБАТЛ</b>\n\n"
        "Отправь мне фотографию — она попадёт в очередь.\n"
        "Когда найдётся второй участник, я автоматически создам батл.\n\n"
        "/cancel — отменить ожидание.",
        parse_mode="HTML"
    )


@dp.message(Command("cancel"))
async def cancel_handler(message: Message):
    deleted = db.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (message.from_user.id,)
    ).rowcount
    db.commit()

    if deleted:
        await message.answer("❌ Ты удалён из очереди.")
    else:
        await message.answer("ℹ️ Тебя нет в очереди.")


@dp.message(Command("admin"))
async def admin_handler(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Нет доступа.")
        return

    await message.answer(
        "⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"🏆 Приз: <b>{get_setting('prize')}</b>\n"
        f"⏰ Итоги: <b>{get_setting('result_time')}</b>\n"
        f"⚡️ Буст: <b>{BOOST_PRICE_PER_VOTE} ⭐ за голос</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(F.data == "admin_prize")
async def admin_prize_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    admin_mode[ADMIN_ID] = "prize"

    await callback.message.answer(
        "🏆 Отправь новое значение приза числом.\n"
        "Например: <code>2000</code>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_time")
async def admin_time_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    admin_mode[ADMIN_ID] = "time"

    await callback.message.answer(
        "⏰ Отправь время окончания в формате <code>22:00</code>.",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    battles = db.execute(
        "SELECT COUNT(*) AS cnt FROM battles"
    ).fetchone()["cnt"]

    normal_votes = db.execute(
        "SELECT COUNT(*) AS cnt FROM votes"
    ).fetchone()["cnt"]

    boost_votes = db.execute(
        "SELECT COALESCE(SUM(votes), 0) AS cnt FROM boosts"
    ).fetchone()["cnt"]

    stars = db.execute(
        "SELECT COALESCE(SUM(stars), 0) AS cnt FROM boosts"
    ).fetchone()["cnt"]

    await callback.message.answer(
        "📊 <b>СТАТИСТИКА</b>\n\n"
        f"⚔️ Батлов: <b>{battles}</b>\n"
        f"🗳 Обычных голосов: <b>{normal_votes}</b>\n"
        f"⚡️ Купленных голосов: <b>{boost_votes}</b>\n"
        f"⭐ Stars: <b>{stars}</b>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(F.from_user.id == ADMIN_ID, F.text)
async def admin_text_handler(message: Message):
    mode = admin_mode.get(ADMIN_ID)
    text = (message.text or "").strip()

    if not mode:
        return

    if mode == "prize":
        if not text.isdigit() or int(text) <= 0:
            await message.answer("❌ Введи положительное число.")
            return

        set_setting("prize", f"{text}₽")
        admin_mode.pop(ADMIN_ID, None)

        await message.answer(
            f"✅ Приз изменён: <b>{text}₽</b>",
            parse_mode="HTML"
        )
        return

    if mode == "time":
        try:
            hours, minutes = map(int, text.split(":"))
        except ValueError:
            await message.answer(
                "❌ Формат должен быть таким: <code>22:00</code>",
                parse_mode="HTML"
            )
            return

        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            await message.answer("❌ Некорректное время.")
            return

        set_setting("result_time", f"{hours:02d}:{minutes:02d}")
        admin_mode.pop(ADMIN_ID, None)

        await message.answer(
            f"✅ Время изменено: <b>{hours:02d}:{minutes:02d}</b>",
            parse_mode="HTML"
        )


@dp.message(F.photo)
async def photo_handler(message: Message):
    user_id = message.from_user.id
    photo_id = message.photo[-1].file_id

    logger.info(
        "PHOTO RECEIVED | user=%s | photo_id=%s",
        user_id,
        photo_id
    )

    existing = db.execute(
        "SELECT 1 FROM waiting WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if existing:
        await message.answer(
            "⏳ Ты уже находишься в очереди.\n"
            "Подожди второго участника или используй /cancel."
        )
        return

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

    if not opponent:
        db.execute(
            """
            INSERT INTO waiting(user_id, photo_id, created_at)
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                photo_id,
                datetime.now().isoformat()
            )
        )

        db.commit()

        await message.answer(
            "⏳ <b>Фото принято!</b>\n\n"
            "Ты первый в очереди.\n"
            "Когда появится второй участник, батл создастся автоматически.",
            parse_mode="HTML"
        )

        logger.info("USER QUEUED | user=%s", user_id)
        return

    db.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (opponent["user_id"],)
    )

    cur = db.execute(
        """
        INSERT INTO battles(
            user1_id,
            user1_photo,
            user2_id,
            user2_photo,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            opponent["user_id"],
            opponent["photo_id"],
            user_id,
            photo_id,
            datetime.now().isoformat()
        )
    )

    battle_id = cur.lastrowid
    db.commit()

    logger.info(
        "BATTLE CREATED | battle=%s | user1=%s | user2=%s",
        battle_id,
        opponent["user_id"],
        user_id
    )

    try:
        sent1 = await bot.send_photo(
            chat_id=CHANNEL,
            photo=opponent["photo_id"],
            caption=(
                f"📸 <b>УЧАСТНИК 1</b>\n"
                f"ФОТОБАТЛ №{battle_id}"
            ),
            parse_mode="HTML"
        )

        sent2 = await bot.send_photo(
            chat_id=CHANNEL,
            photo=photo_id,
            caption=(
                f"📸 <b>УЧАСТНИК 2</b>\n"
                f"ФОТОБАТЛ №{battle_id}"
            ),
            parse_mode="HTML"
        )

        vote_message = await bot.send_message(
            chat_id=CHANNEL,
            text=(
                f"📸 <b>ФОТОБАТЛ №{battle_id}</b>\n\n"
                "1 — 🔥\n"
                "2 — ❤️\n\n"
                f"⏰ Итоги в {get_setting('result_time')}\n"
                f"🏆 Приз — {get_setting('prize')}"
            ),
            parse_mode="HTML",
            reply_markup=vote_keyboard(
                battle_id,
                0,
                0
            )
        )

        db.execute(
            """
            UPDATE battles
            SET
                channel_photo1_message_id = ?,
                channel_photo2_message_id = ?,
                vote_message_id = ?
            WHERE id = ?
            """,
            (
                sent1.message_id,
                sent2.message_id,
                vote_message.message_id,
                battle_id
            )
        )

        db.commit()

    except Exception:
        logger.exception(
            "CHANNEL PUBLISH ERROR | battle=%s",
            battle_id
        )

        await message.answer(
            "❌ Фото получено, но не удалось опубликовать батл.\n"
            "Проверь права бота в канале."
        )
        return

    await message.answer(
        f"🔥 <b>Батл №{battle_id} создан!</b>\n\n"
        "Твоя фотография — участник 2.",
        parse_mode="HTML"
    )

    try:
        await bot.send_message(
            opponent["user_id"],
            f"🔥 <b>Ты участвуешь в батле №{battle_id}!</b>\n"
            "Твоя фотография — участник 1.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(
            "USER1 NOTIFICATION ERROR: %s",
            e
        )

    try:
        await bot.send_message(
            user_id,
            f"🔥 <b>Ты участвуешь в батле №{battle_id}!</b>\n"
            "Твоя фотография — участник 2.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(
            "USER2 NOTIFICATION ERROR: %s",
            e
        )


@dp.callback_query(F.data.startswith("vote_"))
async def vote_handler(callback: CallbackQuery):
    try:
        _, battle_id_text, participant_text = callback.data.split("_")
        battle_id = int(battle_id_text)
        participant = int(participant_text)
    except (ValueError, AttributeError):
        await callback.answer(
            "❌ Некорректный голос.",
            show_alert=True
        )
        return

    if participant not in (1, 2):
        await callback.answer(
            "❌ Некорректный участник.",
            show_alert=True
        )
        return

    battle = db.execute(
        "SELECT id FROM battles WHERE id = ?",
        (battle_id,)
    ).fetchone()

    if not battle:
        await callback.answer(
            "❌ Батл не найден.",
            show_alert=True
        )
        return

    user_id = callback.from_user.id

    old_vote = db.execute(
        """
        SELECT participant
        FROM votes
        WHERE battle_id = ? AND user_id = ?
        """,
        (battle_id, user_id)
    ).fetchone()

    if old_vote and old_vote["participant"] == participant:
        await callback.answer(
            "Ты уже голосовал за этого участника."
        )
        return

    db.execute(
        "DELETE FROM votes WHERE battle_id = ? AND user_id = ?",
        (battle_id, user_id)
    )

    db.execute(
        """
        INSERT INTO votes(battle_id, user_id, participant)
        VALUES (?, ?, ?)
        """,
        (
            battle_id,
            user_id,
            participant
        )
    )

    db.commit()

    await update_vote_buttons(battle_id)

    await callback.answer("✅ Голос учтён!")


@dp.callback_query(F.data.startswith("boost_"))
async def boost_start_handler(callback: CallbackQuery):
    try:
        battle_id = int(
            callback.data.split("_")[1]
        )
    except (ValueError, IndexError):
        await callback.answer(
            "❌ Некорректный батл.",
            show_alert=True
        )
        return

    battle = db.execute(
        "SELECT id FROM battles WHERE id = ?",
        (battle_id,)
    ).fetchone()

    if not battle:
        await callback.answer(
            "❌ Батл не найден.",
            show_alert=True
        )
        return

    try:
        await bot.send_message(
            callback.from_user.id,
            "⚡️ <b>БУСТ РЕАКЦИЙ</b>\n\n"
            "Выбери участника:",
            parse_mode="HTML",
            reply_markup=participant_keyboard(
                battle_id
            )
        )

        await callback.answer(
            "Открыл выбор участника в личке."
        )

    except Exception:
        await callback.answer(
            "❗ Сначала открой бота и нажми /start.",
            show_alert=True
        )


@dp.callback_query(F.data.startswith("boostparticipant_"))
async def boost_participant_handler(
    callback: CallbackQuery
):
    try:
        _, _, battle_id_text, participant_text = (
            callback.data.split("_")
        )

        battle_id = int(battle_id_text)
        participant = int(participant_text)

    except (ValueError, IndexError):
        await callback.answer(
            "❌ Некорректные данные.",
            show_alert=True
        )
        return

    if participant not in (1, 2):
        await callback.answer(
            "❌ Некорректный участник.",
            show_alert=True
        )
        return

    battle = db.execute(
        "SELECT id FROM battles WHERE id = ?",
        (battle_id,)
    ).fetchone()

    if not battle:
        await callback.answer(
            "❌ Батл не найден.",
            show_alert=True
        )
        return

    boost_pending[callback.from_user.id] = {
        "battle_id": battle_id,
        "participant": participant
    }

    name = (
        "🔥 УЧАСТНИК 1"
        if participant == 1
        else "❤️ УЧАСТНИК 2"
    )

    await callback.message.answer(
        f"⚡️ <b>{name}</b>\n\n"
        "Введи количество голосов числом.\n\n"
        f"💰 <b>{BOOST_PRICE_PER_VOTE} ⭐ = 1 голос</b>\n"
        "Например: <code>50</code>\n"
        "Стоимость: <b>100 ⭐</b>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(
    F.text,
    F.from_user.id != ADMIN_ID
)
async def boost_amount_handler(message: Message):
    user_id = message.from_user.id

    if user_id not in boost_pending:
        return

    text = (message.text or "").strip()

    if not text.isdigit():
        await message.answer(
            "❌ Введи количество голосов числом.\n"
            "Например: <code>50</code>",
            parse_mode="HTML"
        )
        return

    votes = int(text)

    if votes <= 0:
        await message.answer(
            "❌ Количество должно быть больше 0."
        )
        return

    if votes > 100000:
        await message.answer(
            "❌ Максимум за одну покупку — 100000 голосов."
        )
        return

    data = boost_pending.pop(user_id)

    battle_id = data["battle_id"]
    participant = data["participant"]

    stars = votes * BOOST_PRICE_PER_VOTE

    battle = db.execute(
        "SELECT id FROM battles WHERE id = ?",
        (battle_id,)
    ).fetchone()

    if not battle:
        await message.answer(
            "❌ Батл уже не найден."
        )
        return

    name = (
        "УЧАСТНИК 1"
        if participant == 1
        else "УЧАСТНИК 2"
    )

    try:
        await bot.send_invoice(
            chat_id=user_id,
            title=f"Буст — {votes} голосов",
            description=(
                f"{name}, батл №{battle_id}"
            ),
            payload=(
                f"boost:"
                f"{battle_id}:"
                f"{participant}:"
                f"{votes}:"
                f"{user_id}"
            ),
            currency="XTR",
            prices=[
                LabeledPrice(
                    label=f"{votes} голосов",
                    amount=stars
                )
            ],
            provider_token=""
        )

    except Exception:
        logger.exception(
            "SEND INVOICE ERROR"
        )

        await message.answer(
            "❌ Не удалось создать платёж. "
            "Попробуй ещё раз."
        )


@dp.pre_checkout_query()
async def pre_checkout_handler(
    query: PreCheckoutQuery
):
    try:
        parts = query.invoice_payload.split(":")

        if (
            len(parts) != 5
            or parts[0] != "boost"
        ):
            raise ValueError

        battle_id = int(parts[1])
        participant = int(parts[2])
        votes = int(parts[3])
        user_id = int(parts[4])

    except (ValueError, IndexError):
        await query.answer(
            ok=False,
            error_message="Некорректный платёж."
        )
        return

    if query.from_user.id != user_id:
        await query.answer(
            ok=False,
            error_message="Пользователь не совпадает."
        )
        return

    if participant not in (1, 2) or votes <= 0:
        await query.answer(
            ok=False,
            error_message="Некорректные данные."
        )
        return

    expected = votes * BOOST_PRICE_PER_VOTE

    if query.total_amount != expected:
        await query.answer(
            ok=False,
            error_message="Неверная сумма."
        )
        return

    battle = db.execute(
        "SELECT id FROM battles WHERE id = ?",
        (battle_id,)
    ).fetchone()

    if not battle:
        await query.answer(
            ok=False,
            error_message="Батл не найден."
        )
        return

    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(
    message: Message
):
    payment = message.successful_payment

    try:
        parts = payment.invoice_payload.split(":")

        if (
            len(parts) != 5
            or parts[0] != "boost"
        ):
            return

        battle_id = int(parts[1])
        participant = int(parts[2])
        votes = int(parts[3])
        user_id = int(parts[4])

    except (ValueError, IndexError):
        logger.exception(
            "PAYMENT PAYLOAD ERROR"
        )
        return

    if message.from_user.id != user_id:
        logger.error(
            "PAYMENT USER MISMATCH"
        )
        return

    expected = votes * BOOST_PRICE_PER_VOTE

    if payment.total_amount != expected:
        logger.error(
            "WRONG PAYMENT AMOUNT | expected=%s received=%s",
            expected,
            payment.total_amount
        )
        return

    battle = db.execute(
        "SELECT id FROM battles WHERE id = ?",
        (battle_id,)
    ).fetchone()

    if not battle:
        await message.answer(
            "❌ Батл не найден."
        )
        return

    db.execute(
        """
        INSERT INTO boosts(
            battle_id,
            user_id,
            participant,
            votes,
            stars,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            battle_id,
            user_id,
            participant,
            votes,
            payment.total_amount,
            datetime.now().isoformat()
        )
    )

    db.commit()

    await update_vote_buttons(
        battle_id
    )

    totals = get_totals(
        battle_id
    )

    name = (
        "🔥 УЧАСТНИК 1"
        if participant == 1
        else "❤️ УЧАСТНИК 2"
    )

    await message.answer(
        "✅ <b>БУСТ УСПЕШНО КУПЛЕН!</b>\n\n"
        f"{name}\n"
        f"Добавлено: <b>+{votes}</b> голосов\n"
        f"Стоимость: <b>{payment.total_amount} ⭐</b>\n\n"
        f"📊 Сейчас:\n"
        f"🔥 {totals[1]} | ❤️ {totals[2]}",
        parse_mode="HTML"
    )

    logger.info(
        "BOOST PAID | battle=%s user=%s participant=%s votes=%s stars=%s",
        battle_id,
        user_id,
        participant,
        votes,
        payment.total_amount
    )


async def main():
    logger.info(
        "================================"
    )
    logger.info(
        "PHOTO BATTLE BOT STARTING"
    )
    logger.info(
        "CHANNEL = %s",
        CHANNEL
    )
    logger.info(
        "BOOST = %s Stars per vote",
        BOOST_PRICE_PER_VOTE
    )
    logger.info(
        "================================"
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
