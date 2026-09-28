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

# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL = "@pbtestboto"
BOT_USERNAME = "pbpriem_bot"

ADMIN_ID = 8641624229

DEFAULT_PRIZE = "1000₽"
DEFAULT_RESULT_TIME = "22:00"

# 1 купленный голос = 2 Telegram Stars
BOOST_PRICE_PER_VOTE = 2


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# =========================================================
# BOT
# =========================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    "battle.db",
    check_same_thread=False
)

db.row_factory = sqlite3.Row


def init_db():

    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS waiting (
            user_id INTEGER PRIMARY KEY,
            photo_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
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
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            battle_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            participant INTEGER NOT NULL,

            PRIMARY KEY (battle_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS boosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            battle_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            participant INTEGER NOT NULL,

            votes INTEGER NOT NULL,
            stars INTEGER NOT NULL,

            created_at TEXT NOT NULL
        )
    """)

    # Настройки по умолчанию
    if get_setting("prize") is None:
        set_setting("prize", DEFAULT_PRIZE)

    if get_setting("result_time") is None:
        set_setting("result_time", DEFAULT_RESULT_TIME)

    db.commit()


def get_setting(key):

    cur = db.cursor()

    cur.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    row = cur.fetchone()

    if row:
        return row["value"]

    return None


def set_setting(key, value):

    cur = db.cursor()

    cur.execute("""
        INSERT INTO settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
    """, (
        key,
        str(value)
    ))

    db.commit()


init_db()


# =========================================================
# ВРЕМЕННЫЕ СОСТОЯНИЯ АДМИНА
# =========================================================

admin_edit_mode = {}


# =========================================================
# СОСТОЯНИЕ ПОКУПКИ БУСТА
# =========================================================

# user_id -> {
#     "battle_id": int,
#     "participant": 1/2
# }

boost_pending = {}


# =========================================================
# KEYBOARDS
# =========================================================

def vote_keyboard(
    battle_id,
    votes1,
    votes2
):

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
                )
            ],
            [
                InlineKeyboardButton(
                    text="БУСТ РЕАКЦИЙ ⚡️",
                    callback_data=f"boost_{battle_id}"
                )
            ]
        ]
    )


def participant_keyboard(battle_id):

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
            ]
        ]
    )


# =========================================================
# ПОЛУЧЕНИЕ ГОЛОСОВ
# =========================================================

def get_normal_votes(battle_id):

    cur = db.cursor()

    cur.execute("""
        SELECT participant, COUNT(*) AS cnt
        FROM votes
        WHERE battle_id = ?
        GROUP BY participant
    """, (
        battle_id,
    ))

    result = {
        1: 0,
        2: 0
    }

    for row in cur.fetchall():

        result[row["participant"]] = row["cnt"]

    return result


def get_boost_votes(battle_id):

    cur = db.cursor()

    cur.execute("""
        SELECT participant, COALESCE(SUM(votes), 0) AS cnt
        FROM boosts
        WHERE battle_id = ?
        GROUP BY participant
    """, (
        battle_id,
    ))

    result = {
        1: 0,
        2: 0
    }

    for row in cur.fetchall():

        result[row["participant"]] = row["cnt"]

    return result


def get_total_votes(battle_id):

    normal = get_normal_votes(battle_id)
    boost = get_boost_votes(battle_id)

    return {
        1: normal[1] + boost[1],
        2: normal[2] + boost[2]
    }


# =========================================================
# /START
# =========================================================

@dp.message(Command("start"))
async def start_handler(message: Message):

    await message.answer(
        "📸 <b>ФОТОБАТЛ</b>\n\n"
        "Отправь мне фотографию, чтобы принять участие "
        "в следующем батле.\n\n"
        "Когда найдётся второй участник, фотографии "
        "будут опубликованы в канале.\n\n"
        "Для отмены ожидания используй /cancel.",
        parse_mode="HTML"
    )


# =========================================================
# /CANCEL
# =========================================================

@dp.message(Command("cancel"))
async def cancel_handler(message: Message):

    user_id = message.from_user.id

    cur = db.cursor()

    cur.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (user_id,)
    )

    db.commit()

    await message.answer(
        "❌ Ожидание отменено."
    )


# =========================================================
# ПРИЁМ ФОТО
# =========================================================

@dp.message(F.photo)
async def photo_handler(message: Message):

    user_id = message.from_user.id

    photo_id = message.photo[-1].file_id

    logger.info(
        f"PHOTO RECEIVED | user={user_id} | photo={photo_id}"
    )

    cur = db.cursor()

    # Проверяем, не стоит ли пользователь уже в очереди
    cur.execute(
        "SELECT user_id FROM waiting WHERE user_id = ?",
        (user_id,)
    )

    if cur.fetchone():

        await message.answer(
            "⏳ Ты уже находишься в очереди."
        )

        return

    # Ищем другого пользователя
    cur.execute("""
        SELECT user_id, photo_id
        FROM waiting
        ORDER BY created_at
        LIMIT 1
    """)

    opponent = cur.fetchone()

    # =====================================================
    # ЕСЛИ НИКОГО НЕТ — СТАВИМ В ОЧЕРЕДЬ
    # =====================================================

    if not opponent:

        cur.execute("""
            INSERT INTO waiting(
                user_id,
                photo_id,
                created_at
            )
            VALUES (?, ?, ?)
        """, (
            user_id,
            photo_id,
            datetime.now().isoformat()
        ))

        db.commit()

        await message.answer(
            "⏳ <b>Фото принято!</b>\n\n"
            "Ты первый в очереди.\n"
            "Ждём второго участника.",
            parse_mode="HTML"
        )

        logger.info(
            f"USER QUEUED | user={user_id}"
        )

        return

    # =====================================================
    # ПРОВЕРКА, ЧТО ЭТО НЕ САМ ПОЛЬЗОВАТЕЛЬ
    # =====================================================

    if opponent["user_id"] == user_id:

        await message.answer(
            "⏳ Ты уже находишься в очереди."
        )

        return

    # =====================================================
    # УДАЛЯЕМ ИЗ ОЧЕРЕДИ
    # =====================================================

    cur.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (opponent["user_id"],)
    )

    # =====================================================
    # СОЗДАЁМ БАТЛ
    # =====================================================

    cur.execute("""
        INSERT INTO battles(
            user1_id,
            user1_photo,
            user2_id,
            user2_photo,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        opponent["user_id"],
        opponent["photo_id"],
        user_id,
        photo_id,
        datetime.now().isoformat()
    ))

    battle_id = cur.lastrowid

    db.commit()

    logger.info(
        f"BATTLE CREATED | battle={battle_id} | "
        f"user1={opponent['user_id']} | user2={user_id}"
    )

    # =====================================================
    # ПУБЛИКУЕМ ФОТО 1
    # =====================================================

    sent1 = await bot.send_photo(
        chat_id=CHANNEL,
        photo=opponent["photo_id"],
        caption=(
            f"📸 <b>УЧАСТНИК 1</b>\n\n"
            f"ФОТОБАТЛ №{battle_id}"
        ),
        parse_mode="HTML"
    )

    # =====================================================
    # ПУБЛИКУЕМ ФОТО 2
    # =====================================================

    sent2 = await bot.send_photo(
        chat_id=CHANNEL,
        photo=photo_id,
        caption=(
            f"📸 <b>УЧАСТНИК 2</b>\n\n"
            f"ФОТОБАТЛ №{battle_id}"
        ),
        parse_mode="HTML"
    )

    # =====================================================
    # СОЗДАЁМ ГОЛОСОВАНИЕ
    # =====================================================

    result_time = get_setting("result_time")
    prize = get_setting("prize")

    vote_message = await bot.send_message(
        chat_id=CHANNEL,

        text=(
            f"📸 <b>ФОТОБАТЛ №{battle_id}</b>\n\n"
            f"1 — 🔥\n"
            f"2 — ❤️\n\n"
            f"⏰ Итоги в {result_time}\n"
            f"🏆 Приз — {prize}"
        ),

        parse_mode="HTML",

        reply_markup=vote_keyboard(
            battle_id,
            0,
            0
        )
    )

    # =====================================================
    # СОХРАНЯЕМ MESSAGE ID
    # =====================================================

    cur.execute("""
        UPDATE battles

        SET
            channel_photo1_message_id = ?,
            channel_photo2_message_id = ?,
            vote_message_id = ?

        WHERE id = ?
    """, (
        sent1.message_id,
        sent2.message_id,
        vote_message.message_id,
        battle_id
    ))

    db.commit()

    # =====================================================
    # УВЕДОМЛЕНИЯ УЧАСТНИКАМ
    # =====================================================

    try:

        await bot.send_message(
            opponent["user_id"],
            f"🔥 <b>Ты участвуешь в батле №{battle_id}!</b>\n\n"
            f"Твоя фотография — участник 1.",
            parse_mode="HTML"
        )

    except Exception as e:

        logger.warning(
            f"Cannot notify user1: {e}"
        )

    try:

        await bot.send_message(
            user_id,
            f"🔥 <b>Ты участвуешь в батле №{battle_id}!</b>\n\n"
            f"Твоя фотография — участник 2.",
            parse_mode="HTML"
        )

    except Exception as e:

        logger.warning(
            f"Cannot notify user2: {e}"
        )

    await message.answer(
        "🔥 Батл создан!"
    )


# =========================================================
# ОБЫЧНОЕ ГОЛОСОВАНИЕ
# =========================================================

@dp.callback_query(F.data.startswith("vote_"))
async def vote_handler(callback: CallbackQuery):

    parts = callback.data.split("_")

    battle_id = int(parts[1])
    participant = int(parts[2])

    user_id = callback.from_user.id

    cur = db.cursor()

    # Проверяем существование батла
    cur.execute(
        "SELECT vote_message_id FROM battles WHERE id = ?",
        (battle_id,)
    )

    battle = cur.fetchone()

    if not battle:

        await callback.answer(
            "Батл не найден.",
            show_alert=True
        )

        return

    # =====================================================
    # ПРОВЕРЯЕМ СТАРЫЙ ГОЛОС
    # =====================================================

    cur.execute("""
        SELECT participant

        FROM votes

        WHERE battle_id = ?
        AND user_id = ?
    """, (
        battle_id,
        user_id
    ))

    old_vote = cur.fetchone()

    # Если нажал на тот же вариант
    if old_vote and old_vote["participant"] == participant:

        await callback.answer(
            "Ты уже голосовал за этого участника.",
            show_alert=True
        )

        return

    # Если был другой голос — удаляем
    if old_vote:

        cur.execute("""
            DELETE FROM votes

            WHERE battle_id = ?
            AND user_id = ?
        """, (
            battle_id,
            user_id
        ))

    # Добавляем новый
    cur.execute("""
        INSERT INTO votes(
            battle_id,
            user_id,
            participant
        )
        VALUES (?, ?, ?)
    """, (
        battle_id,
        user_id,
        participant
    ))

    db.commit()

    # =====================================================
    # ПОЛУЧАЕМ ОБЩИЕ ГОЛОСА
    # =====================================================

    totals = get_total_votes(battle_id)

    # =====================================================
    # ОБНОВЛЯЕМ КНОПКИ
    # =====================================================

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
            f"Cannot update vote keyboard: {e}"
        )

    await callback.answer(
        "Голос учтён! 🔥"
    )


# =========================================================
# НАЖАТИЕ «БУСТ РЕАКЦИЙ»
# =========================================================

@dp.callback_query(F.data.startswith("boost_"))
async def boost_start(callback: CallbackQuery):

    battle_id = int(
        callback.data.split("_")[1]
    )

    # Проверяем батл
    cur = db.cursor()

    cur.execute(
        "SELECT id FROM battles WHERE id = ?",
        (battle_id,)
    )

    if not cur.fetchone():

        await callback.answer(
            "Батл не найден.",
            show_alert=True
        )

        return

    await callback.message.answer(
        "⚡️ <b>БУСТ РЕАКЦИЙ</b>\n\n"
        "Выбери участника, которому хочешь добавить голоса:",
        parse_mode="HTML",

        reply_markup=participant_keyboard(
            battle_id
        )
    )

    await callback.answer()


# =========================================================
# ВЫБОР УЧАСТНИКА ДЛЯ БУСТА
# =========================================================

@dp.callback_query(
    F.data.startswith("boostparticipant_")
)
async def boost_participant(callback: CallbackQuery):

    parts = callback.data.split("_")

    battle_id = int(parts[1])
    participant = int(parts[2])

    user_id = callback.from_user.id

    boost_pending[user_id] = {
        "battle_id": battle_id,
        "participant": participant
    }

    participant_name = (
        "🔥 УЧАСТНИК 1"
        if participant == 1
        else "❤️ УЧАСТНИК 2"
    )

    await callback.message.answer(
        f"⚡️ <b>{participant_name}</b>\n\n"
        f"Введите количество голосов, которое хотите добавить.\n\n"
        f"💰 Цена: <b>{BOOST_PRICE_PER_VOTE} ⭐ за 1 голос</b>\n\n"
        f"Например, отправьте:\n"
        f"<code>50</code>\n\n"
        f"Это будет стоить <b>100 ⭐</b>.",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ВВОД КОЛИЧЕСТВА ГОЛОСОВ ДЛЯ БУСТА
# =========================================================

@dp.message(F.text)
async def boost_amount_handler(message: Message):

    user_id = message.from_user.id

    # Если пользователь сейчас не покупает буст
    if user_id not in boost_pending:
        return

    text = (message.text or "").strip()

    # Проверяем число
    if not text.isdigit():

        await message.answer(
            "❌ Введи количество голосов числом.\n\n"
            "Например: <code>50</code>",
            parse_mode="HTML"
        )

        return

    votes = int(text)

    if votes <= 0:

        await message.answer(
            "❌ Количество голосов должно быть больше 0."
        )

        return

    # Защита от слишком огромных значений
    if votes > 100000:

        await message.answer(
            "❌ Максимум за одну покупку — 100000 голосов."
        )

        return

    data = boost_pending[user_id]

    battle_id = data["battle_id"]
    participant = data["participant"]

    stars = votes * BOOST_PRICE_PER_VOTE

    # Удаляем состояние
    del boost_pending[user_id]

    participant_name = (
        "🔥 УЧАСТНИК 1"
        if participant == 1
        else "❤️ УЧАСТНИК 2"
    )

    # =====================================================
    # СОЗДАЁМ ПЛАТЁЖ
    # =====================================================

    await bot.send_invoice(

        chat_id=user_id,

        title=f"Буст — {votes} голосов",

        description=(
            f"{participant_name}\n"
            f"Батл №{battle_id}\n\n"
            f"Количество голосов: {votes}"
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


# =========================================================
# PRE-CHECKOUT
# =========================================================

@dp.pre_checkout_query()
async def pre_checkout_handler(
    query: PreCheckoutQuery
):

    payload = query.invoice_payload

    if not payload.startswith("boost:"):

        await query.answer(
            ok=False,
            error_message="Некорректный платёж."
        )

        return

    try:

        parts = payload.split(":")

        if len(parts) != 5:

            raise ValueError()

        battle_id = int(parts[1])
        participant = int(parts[2])
        votes = int(parts[3])
        user_id = int(parts[4])

    except Exception:

        await query.answer(
            ok=False,
            error_message="Некорректные данные платежа."
        )

        return

    # Проверяем пользователя
    if query.from_user.id != user_id:

        await query.answer(
            ok=False,
            error_message="Этот платёж предназначен другому пользователю."
        )

        return

    # Проверяем сумму
    expected_stars = votes * BOOST_PRICE_PER_VOTE

    if query.total_amount != expected_stars:

        await query.answer(
            ok=False,
            error_message="Сумма платежа не совпадает."
        )

        return

    # Проверяем батл
    cur = db.cursor()

    cur.execute(
        "SELECT id FROM battles WHERE id = ?",
        (battle_id,)
    )

    if not cur.fetchone():

        await query.answer(
            ok=False,
            error_message="Батл не найден."
        )

        return

    await query.answer(
        ok=True
    )


# =========================================================
# УСПЕШНАЯ ОПЛАТА
# =========================================================

@dp.message(
    F.successful_payment
)
async def successful_payment_handler(
    message: Message
):

    payment = message.successful_payment

    payload = payment.invoice_payload

    if not payload.startswith("boost:"):

        return

    try:

        parts = payload.split(":")

        battle_id = int(parts[1])
        participant = int(parts[2])
        votes = int(parts[3])
        user_id = int(parts[4])

    except Exception as e:

        logger.error(
            f"PAYLOAD ERROR | {e}"
        )

        return

    # =====================================================
    # ПРОВЕРЯЕМ СУММУ
    # =====================================================

    expected_stars = votes * BOOST_PRICE_PER_VOTE

    if payment.total_amount != expected_stars:

        logger.error(
            f"WRONG PAYMENT | "
            f"expected={expected_stars} "
            f"received={payment.total_amount}"
        )

        await message.answer(
            "❌ Ошибка проверки платежа."
        )

        return

    # =====================================================
    # ДОБАВЛЯЕМ БУСТ
    # =====================================================

    cur = db.cursor()

    cur.execute("""
        INSERT INTO boosts(
            battle_id,
            user_id,
            participant,
            votes,
            stars,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        battle_id,
        user_id,
        participant,
        votes,
        payment.total_amount,
        datetime.now().isoformat()
    ))

    db.commit()

    logger.info(
        f"BOOST PAID | "
        f"battle={battle_id} | "
        f"user={user_id} | "
        f"participant={participant} | "
        f"votes={votes} | "
        f"stars={payment.total_amount}"
    )

    # =====================================================
    # ПОЛУЧАЕМ НОВЫЕ ГОЛОСА
    # =====================================================

    totals = get_total_votes(battle_id)

    # =====================================================
    # НАХОДИМ СООБЩЕНИЕ ГОЛОСОВАНИЯ
    # =====================================================

    cur.execute("""
        SELECT vote_message_id
        FROM battles
        WHERE id = ?
    """, (
        battle_id,
    ))

    battle = cur.fetchone()

    if not battle:

        await message.answer(
            f"✅ Оплата прошла.\n"
            f"Добавлено голосов: +{votes}"
        )

        return

    # =====================================================
    # СРАЗУ ОБНОВЛЯЕМ КНОПКИ
    # =====================================================

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

        logger.error(
            f"UPDATE BOOST BUTTONS ERROR | {e}"
        )

    # =====================================================
    # СООБЩЕНИЕ ПОКУПАТЕЛЮ
    # =====================================================

    participant_name = (
        "🔥 УЧАСТНИК 1"
        if participant == 1
        else "❤️ УЧАСТНИК 2"
    )

    await message.answer(
        f"✅ <b>Буст успешно куплен!</b>\n\n"
        f"{participant_name}\n"
        f"Добавлено: <b>+{votes} голосов</b>\n"
        f"Потрачено: <b>{payment.total_amount} ⭐</b>\n\n"
        f"📊 Текущий счёт:\n"
        f"🔥 {totals[1]} | ❤️ {totals[2]}",
        parse_mode="HTML"
    )


# =========================================================
# ADMIN PANEL
# =========================================================

def admin_keyboard():

    prize = get_setting("prize")
    result_time = get_setting("result_time")

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text=f"🏆 Приз: {prize}",
                    callback_data="admin_prize"
                )
            ],

            [
                InlineKeyboardButton(
                    text=f"⏰ Время: {result_time}",
                    callback_data="admin_time"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin_stats"
                )
            ]

        ]
    )


# =========================================================
# /ADMIN
# =========================================================

@dp.message(Command("admin"))
async def admin_handler(message: Message):

    if message.from_user.id != ADMIN_ID:

        await message.answer(
            "Нет доступа."
        )

        return

    await message.answer(
        "⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"🏆 Приз: <b>{get_setting('prize')}</b>\n"
        f"⏰ Итоги: <b>{get_setting('result_time')}</b>\n\n"
        f"⚡️ Цена буста: <b>{BOOST_PRICE_PER_VOTE} ⭐ / голос</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


# =========================================================
# ADMIN — ПРИЗ
# =========================================================

@dp.callback_query(
    F.data == "admin_prize"
)
async def admin_prize(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    admin_edit_mode[ADMIN_ID] = "prize"

    await callback.message.answer(
        "🏆 Введи новый размер приза.\n\n"
        "Например:\n"
        "<code>2000</code>",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN — ВРЕМЯ
# =========================================================

@dp.callback_query(
    F.data == "admin_time"
)
async def admin_time(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    admin_edit_mode[ADMIN_ID] = "time"

    await callback.message.answer(
        "⏰ Введи новое время окончания.\n\n"
        "Формат:\n"
        "<code>22:00</code>",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN — СТАТИСТИКА
# =========================================================

@dp.callback_query(
    F.data == "admin_stats"
)
async def admin_stats(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "Нет доступа.",
            show_alert=True
        )

        return

    cur = db.cursor()

    cur.execute(
        "SELECT COUNT(*) AS cnt FROM battles"
    )

    battles = cur.fetchone()["cnt"]

    cur.execute(
        "SELECT COUNT(*) AS cnt FROM votes"
    )

    votes = cur.fetchone()["cnt"]

    cur.execute(
        "SELECT COALESCE(SUM(votes), 0) AS cnt FROM boosts"
    )

    boost_votes = cur.fetchone()["cnt"]

    cur.execute(
        "SELECT COALESCE(SUM(stars), 0) AS cnt FROM boosts"
    )

    stars = cur.fetchone()["cnt"]

    await callback.message.answer(
        "📊 <b>СТАТИСТИКА</b>\n\n"
        f"⚔️ Батлов: <b>{battles}</b>\n"
        f"🗳 Обычных голосов: <b>{votes}</b>\n"
        f"⚡️ Купленных голосов: <b>{boost_votes}</b>\n"
        f"⭐ Получено Stars: <b>{stars}</b>",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN TEXT
# =========================================================

@dp.message(
    F.from_user.id == ADMIN_ID,
    F.text
)
async def admin_text_handler(message: Message):

    user_id = message.from_user.id

    text = (message.text or "").strip()

    if not text:
        return

    # =====================================================
    # РЕЖИМ ПРИЗА
    # =====================================================

    if admin_edit_mode.get(user_id) == "prize":

        if not text.isdigit():

            await message.answer(
                "❌ Приз должен быть числом."
            )

            return

        set_setting(
            "prize",
            text
        )

        del admin_edit_mode[user_id]

        await message.answer(
            f"✅ Приз изменён на "
            f"<b>{text}₽</b>.",
            parse_mode="HTML"
        )

        return

    # =====================================================
    # РЕЖИМ ВРЕМЕНИ
    # =====================================================

    if admin_edit_mode.get(user_id) == "time":

        if (
            len(text) != 5
            or text[2] != ":"
        ):

            await message.answer(
                "❌ Неверный формат.\n\n"
                "Используй, например:\n"
                "<code>22:00</code>",
                parse_mode="HTML"
            )

            return

        try:

            hours = int(text[:2])
            minutes = int(text[3:])

        except ValueError:

            await message.answer(
                "❌ Неверное время."
            )

            return

        if not (
            0 <= hours <= 23
            and 0 <= minutes <= 59
        ):

            await message.answer(
                "❌ Неверное время."
            )

            return

        set_setting(
            "result_time",
            text
        )

        del admin_edit_mode[user_id]

        await message.answer(
            f"✅ Время окончания изменено на "
            f"<b>{text}</b>.",
            parse_mode="HTML"
        )

        return


# =========================================================
# ЗАПУСК
# =========================================================

async def main():

    logger.info(
        "BOT STARTING..."
    )

    logger.info(
        f"CHANNEL: {CHANNEL}"
    )

    logger.info(
        f"ADMIN ID: {ADMIN_ID}"
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    asyncio.run(main())
