import os
import sqlite3
import asyncio
import uuid
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    LabeledPrice,
    PreCheckoutQuery,
)
from aiogram.filters import CommandStart, Command


# =========================================================
# НАСТРОЙКИ
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL = "@pbtestboto"

ADMIN_ID = 8641624229

DB_NAME = "battle.db"

DEFAULT_PRIZE = "1000₽"
DEFAULT_RESULT_TIME = "22:00"

DEFAULT_BOOSTS = {
    10: 20,
    25: 45,
    50: 80,
    100: 140,
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

BOT_USERNAME = ""


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = db()
    cur = conn.cursor()

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS boosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            participant INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            stars INTEGER NOT NULL,
            charge_id TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS boost_orders (
            payload TEXT PRIMARY KEY,
            battle_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            participant INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            stars INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            charge_id TEXT
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('prize', ?)
    """, (DEFAULT_PRIZE,))

    cur.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('result_time', ?)
    """, (DEFAULT_RESULT_TIME,))

    for amount, stars in DEFAULT_BOOSTS.items():
        cur.execute("""
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
        """, (f"boost_{amount}", str(stars)))

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    row = cur.fetchone()
    conn.close()

    if row:
        return row[0]

    return default


def set_setting(key, value):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
    """, (key, str(value)))

    conn.commit()
    conn.close()


def get_boost_price(amount):
    value = get_setting(
        f"boost_{amount}",
        DEFAULT_BOOSTS.get(amount)
    )

    try:
        return int(value)
    except:
        return DEFAULT_BOOSTS.get(amount, 0)


def get_battle(battle_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            user1,
            user2,
            photo1,
            photo2,
            message_id,
            votes1,
            votes2,
            active
        FROM battles
        WHERE id = ?
    """, (battle_id,))

    row = cur.fetchone()
    conn.close()

    return row


# =========================================================
# KEYBOARDS
# =========================================================

def vote_keyboard_counts(battle_id, votes1, votes2):
    boost_url = f"https://t.me/{BOT_USERNAME}?start=boost_{battle_id}"

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
            ],
            [
                InlineKeyboardButton(
                    text="БУСТ РЕАКЦИЙ ⚡️",
                    url=boost_url
                )
            ]
        ]
    )


def boost_participant_keyboard(battle_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔥 УЧАСТНИК 1",
                    callback_data=f"boostparticipant:{battle_id}:1"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❤️ УЧАСТНИК 2",
                    callback_data=f"boostparticipant:{battle_id}:2"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="boostcancel"
                )
            ]
        ]
    )


def boost_amount_keyboard(battle_id, participant):
    buttons = []

    for amount in [10, 25, 50, 100]:
        stars = get_boost_price(amount)

        buttons.append([
            InlineKeyboardButton(
                text=f"+{amount} ⚡️ — {stars} ⭐",
                callback_data=f"boostbuy:{battle_id}:{participant}:{amount}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"boostback:{battle_id}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
                    text="⏰ Изменить время",
                    callback_data="admin_time"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚡️ Цены бустов",
                    callback_data="admin_boosts"
                )
            ]
        ]
    )


def admin_boost_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="+10",
                    callback_data="admin_boost_10"
                ),
                InlineKeyboardButton(
                    text="+25",
                    callback_data="admin_boost_25"
                )
            ],
            [
                InlineKeyboardButton(
                    text="+50",
                    callback_data="admin_boost_50"
                ),
                InlineKeyboardButton(
                    text="+100",
                    callback_data="admin_boost_100"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="admin_back"
                )
            ]
        ]
    )


# =========================================================
# /START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):

    text = message.text or ""

    if text.startswith("/start boost_"):

        try:
            battle_id = int(
                text.replace("/start boost_", "").strip()
            )
        except ValueError:
            await message.answer(
                "❌ Неверный номер батла."
            )
            return

        battle = get_battle(battle_id)

        if not battle:
            await message.answer(
                "❌ Такой батл не найден."
            )
            return

        if battle[8] != 1:
            await message.answer(
                "❌ Этот батл уже завершён."
            )
            return

        await message.answer(
            f"⚡️ <b>БУСТ РЕАКЦИЙ</b>\n\n"
            f"Батл №{battle_id}\n\n"
            f"Выбери участника, которому хочешь добавить бусты:",
            reply_markup=boost_participant_keyboard(battle_id),
            parse_mode="HTML"
        )

        return

    await message.answer(
        "👋 <b>Добро пожаловать в фотобатлы!</b>\n\n"
        "Отправь мне одну фотографию — она попадёт в очередь.\n"
        "Когда найдётся соперник, автоматически создастся батл.",
        parse_mode="HTML"
    )


# =========================================================
# /CANCEL
# =========================================================

@dp.message(Command("cancel"))
async def cancel_handler(message: Message):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (message.from_user.id,)
    )

    deleted = cur.rowcount

    conn.commit()
    conn.close()

    if deleted:
        await message.answer(
            "❌ Ты удалён из очереди."
        )
    else:
        await message.answer(
            "ℹ️ Ты сейчас не находишься в очереди."
        )


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("admin"))
async def admin_handler(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    prize = get_setting("prize", DEFAULT_PRIZE)
    result_time = get_setting(
        "result_time",
        DEFAULT_RESULT_TIME
    )

    await message.answer(
        f"⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"💰 Приз: <b>{prize}</b>\n"
        f"⏰ Окончание: <b>{result_time}</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    prize = get_setting("prize", DEFAULT_PRIZE)
    result_time = get_setting(
        "result_time",
        DEFAULT_RESULT_TIME
    )

    await callback.message.edit_text(
        f"⚙️ <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"💰 Приз: <b>{prize}</b>\n"
        f"⏰ Окончание: <b>{result_time}</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_prize")
async def admin_prize(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    await callback.message.answer(
        "💰 Отправь новый размер приза.\n\n"
        "Например:\n"
        "<code>2000₽</code>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_time")
async def admin_time(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    await callback.message.answer(
        "⏰ Отправь время окончания батла в формате:\n\n"
        "<code>22:00</code>",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(F.data == "admin_boosts")
async def admin_boosts(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    text = (
        "⚡️ <b>ЦЕНЫ БУСТОВ</b>\n\n"
        f"+10 ⚡️ — <b>{get_boost_price(10)} ⭐</b>\n"
        f"+25 ⚡️ — <b>{get_boost_price(25)} ⭐</b>\n"
        f"+50 ⚡️ — <b>{get_boost_price(50)} ⭐</b>\n"
        f"+100 ⚡️ — <b>{get_boost_price(100)} ⭐</b>\n\n"
        "Выбери тариф для изменения."
    )

    await callback.message.edit_text(
        text,
        reply_markup=admin_boost_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN — ВЫБОР ТАРИФА
# =========================================================

@dp.callback_query(F.data.startswith("admin_boost_"))
async def admin_boost_select(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    amount = int(
        callback.data.split("_")[-1]
    )

    await callback.message.answer(
        f"⚡️ Тариф <b>+{amount}</b>\n\n"
        f"Сейчас: <b>{get_boost_price(amount)} ⭐</b>\n\n"
        f"Отправь новую цену в Stars.\n"
        f"Например: <code>30</code>",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN TEXT
# ВАЖНО: фильтр F.text + F.from_user.id
# =========================================================

@dp.message(F.from_user.id == ADMIN_ID, F.text)
async def admin_text_handler(message: Message):

    text = (message.text or "").strip()

    if not text:
        return

    # Время
    if len(text) == 5 and text[2] == ":":
        try:
            hours = int(text[:2])
            minutes = int(text[3:])

            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                set_setting("result_time", text)

                await message.answer(
                    f"✅ Время окончания изменено на <b>{text}</b>.",
                    parse_mode="HTML"
                )
                return

        except ValueError:
            pass

    # Число = новый приз
    if text.isdigit():

        set_setting("prize", text)

        await message.answer(
            f"✅ Приз изменён на <b>{text}</b>.",
            parse_mode="HTML"
        )


# =========================================================
# ADMIN COMMAND: /boostprice
# =========================================================

@dp.message(Command("boostprice"))
async def boostprice_handler(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    parts = (message.text or "").split()

    if len(parts) != 3:
        await message.answer(
            "Использование:\n\n"
            "<code>/boostprice 10 25</code>\n\n"
            "Где:\n"
            "10 — количество бустов\n"
            "25 — цена в Stars",
            parse_mode="HTML"
        )
        return

    try:
        amount = int(parts[1])
        stars = int(parts[2])
    except ValueError:
        await message.answer(
            "❌ Используй числа."
        )
        return

    if amount not in [10, 25, 50, 100]:
        await message.answer(
            "❌ Доступные пакеты: 10, 25, 50, 100."
        )
        return

    if stars < 1:
        await message.answer(
            "❌ Цена должна быть больше 0."
        )
        return

    set_setting(
        f"boost_{amount}",
        stars
    )

    await message.answer(
        f"✅ Тариф <b>+{amount} ⚡️</b> теперь стоит "
        f"<b>{stars} ⭐</b>.",
        parse_mode="HTML"
    )


# =========================================================
# PHOTO
# =========================================================

@dp.message(F.photo)
async def photo_handler(message: Message):

    user_id = message.from_user.id
    username = message.from_user.username or ""

    photo_id = message.photo[-1].file_id

    print(
        f"PHOTO RECEIVED | user={user_id} | photo={photo_id}"
    )

    conn = db()
    cur = conn.cursor()

    # Проверяем очередь
    cur.execute(
        "SELECT user_id FROM waiting WHERE user_id = ?",
        (user_id,)
    )

    if cur.fetchone():
        conn.close()

        await message.answer(
            "⏳ Ты уже находишься в очереди.\n"
            "Подожди соперника."
        )

        return

    # Ищем соперника
    cur.execute("""
        SELECT user_id, username, photo_id
        FROM waiting
        ORDER BY rowid
        LIMIT 1
    """)

    waiting_user = cur.fetchone()

    # Если соперника нет
    if not waiting_user:

        cur.execute("""
            INSERT INTO waiting (
                user_id,
                username,
                photo_id
            )
            VALUES (?, ?, ?)
        """, (
            user_id,
            username,
            photo_id
        ))

        conn.commit()
        conn.close()

        await message.answer(
            "✅ Фото принято!\n\n"
            "⏳ Ищу тебе соперника..."
        )

        print(
            f"PHOTO QUEUED | user={user_id}"
        )

        return

    opponent_id = waiting_user[0]
    opponent_username = waiting_user[1]
    opponent_photo = waiting_user[2]

    if opponent_id == user_id:
        conn.close()

        await message.answer(
            "❌ Нельзя создать батл с самим собой."
        )

        return

    # Удаляем соперника из очереди
    cur.execute(
        "DELETE FROM waiting WHERE user_id = ?",
        (opponent_id,)
    )

    # Создаём батл
    cur.execute("""
        INSERT INTO battles (
            user1,
            user2,
            photo1,
            photo2,
            votes1,
            votes2,
            active
        )
        VALUES (?, ?, ?, ?, 0, 0, 1)
    """, (
        opponent_id,
        user_id,
        opponent_photo,
        photo_id
    ))

    battle_id = cur.lastrowid

    conn.commit()
    conn.close()

    print(
        f"BATTLE CREATED | battle={battle_id} | "
        f"user1={opponent_id} | user2={user_id}"
    )

    # Публикуем фотографии
    media = [
        InputMediaPhoto(
            media=opponent_photo
        ),
        InputMediaPhoto(
            media=photo_id
        )
    ]

    try:

        await bot.send_media_group(
            chat_id=CHANNEL,
            media=media
        )

        prize = get_setting(
            "prize",
            DEFAULT_PRIZE
        )

        result_time = get_setting(
            "result_time",
            DEFAULT_RESULT_TIME
        )

        vote_message = await bot.send_message(
            chat_id=CHANNEL,
            text=(
                f"📸 <b>ФОТОБАТЛ №{battle_id}</b>\n\n"
                f"1 — 🔥\n"
                f"2 — ❤️\n\n"
                f"Итоги в <b>{result_time}</b>\n"
                f"Приз — <b>{prize}</b>\n\n"
                f"⚡️ Платные бусты отображаются отдельно."
            ),
            reply_markup=vote_keyboard_counts(
                battle_id,
                0,
                0
            ),
            parse_mode="HTML"
        )

        conn = db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE battles
            SET message_id = ?
            WHERE id = ?
        """, (
            vote_message.message_id,
            battle_id
        ))

        conn.commit()
        conn.close()

        await message.answer(
            "🔥 Батл создан!\n\n"
            f"Твой батл №{battle_id} уже опубликован."
        )

        print(
            f"BATTLE PUBLISHED | battle={battle_id}"
        )

    except Exception as e:

        print(
            f"Ошибка публикации батла: {repr(e)}"
        )

        await message.answer(
            "❌ Не удалось опубликовать батл."
        )


# =========================================================
# VOTING
# =========================================================

@dp.callback_query(F.data.startswith("vote:"))
async def vote_handler(callback: CallbackQuery):

    parts = callback.data.split(":")

    battle_id = int(parts[1])
    choice = int(parts[2])

    user_id = callback.from_user.id

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            votes1,
            votes2,
            active,
            message_id
        FROM battles
        WHERE id = ?
    """, (battle_id,))

    battle = cur.fetchone()

    if not battle:
        conn.close()

        await callback.answer(
            "Батл не найден.",
            show_alert=True
        )

        return

    votes1 = battle[0]
    votes2 = battle[1]
    active = battle[2]
    message_id = battle[3]

    if not active:
        conn.close()

        await callback.answer(
            "❌ Батл уже завершён.",
            show_alert=True
        )

        return

    cur.execute("""
        SELECT choice
        FROM votes
        WHERE battle_id = ?
        AND user_id = ?
    """, (
        battle_id,
        user_id
    ))

    old_vote = cur.fetchone()

    if old_vote:

        old_choice = old_vote[0]

        if old_choice == choice:
            conn.close()

            await callback.answer(
                "Ты уже голосуешь за этого участника."
            )

            return

        if old_choice == 1:
            votes1 -= 1
        else:
            votes2 -= 1

        cur.execute("""
            UPDATE votes
            SET choice = ?
            WHERE battle_id = ?
            AND user_id = ?
        """, (
            choice,
            battle_id,
            user_id
        ))

    else:

        cur.execute("""
            INSERT INTO votes (
                battle_id,
                user_id,
                choice
            )
            VALUES (?, ?, ?)
        """, (
            battle_id,
            user_id,
            choice
        ))

    if choice == 1:
        votes1 += 1
    else:
        votes2 += 1

    cur.execute("""
        UPDATE battles
        SET votes1 = ?,
            votes2 = ?
        WHERE id = ?
    """, (
        votes1,
        votes2,
        battle_id
    ))

    conn.commit()
    conn.close()

    try:

        await bot.edit_message_reply_markup(
            chat_id=CHANNEL,
            message_id=message_id,
            reply_markup=vote_keyboard_counts(
                battle_id,
                votes1,
                votes2
            )
        )

    except Exception as e:

        print(
            f"Не удалось обновить кнопки: {repr(e)}"
        )

    await callback.answer(
        "🔥 Голос изменён."
        if old_vote
        else "🔥 Голос принят."
    )


# =========================================================
# BOOST — ВЫБОР УЧАСТНИКА
# =========================================================

@dp.callback_query(F.data.startswith("boostparticipant:"))
async def boost_participant_handler(
    callback: CallbackQuery
):

    parts = callback.data.split(":")

    battle_id = int(parts[1])
    participant = int(parts[2])

    battle = get_battle(battle_id)

    if not battle or battle[8] != 1:
        await callback.answer(
            "❌ Батл уже завершён.",
            show_alert=True
        )
        return

    await callback.message.edit_text(
        f"⚡️ <b>БУСТ РЕАКЦИЙ</b>\n\n"
        f"Батл №{battle_id}\n"
        f"Выбран участник <b>№{participant}</b>.\n\n"
        f"Выбери количество бустов:",
        reply_markup=boost_amount_keyboard(
            battle_id,
            participant
        ),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# BOOST — НАЗАД
# =========================================================

@dp.callback_query(F.data.startswith("boostback:"))
async def boost_back_handler(
    callback: CallbackQuery
):

    battle_id = int(
        callback.data.split(":")[1]
    )

    battle = get_battle(battle_id)

    if not battle or battle[8] != 1:
        await callback.answer(
            "❌ Батл уже завершён.",
            show_alert=True
        )
        return

    await callback.message.edit_text(
        f"⚡️ <b>БУСТ РЕАКЦИЙ</b>\n\n"
        f"Батл №{battle_id}\n\n"
        f"Выбери участника:",
        reply_markup=boost_participant_keyboard(
            battle_id
        ),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# BOOST — ОТМЕНА
# =========================================================

@dp.callback_query(F.data == "boostcancel")
async def boost_cancel_handler(
    callback: CallbackQuery
):

    await callback.message.edit_text(
        "❌ Покупка буста отменена."
    )

    await callback.answer()


# =========================================================
# BOOST — СОЗДАНИЕ INVOICE
# =========================================================

@dp.callback_query(F.data.startswith("boostbuy:"))
async def boost_buy_handler(
    callback: CallbackQuery
):

    parts = callback.data.split(":")

    battle_id = int(parts[1])
    participant = int(parts[2])
    amount = int(parts[3])

    user_id = callback.from_user.id

    battle = get_battle(battle_id)

    if not battle:
        await callback.answer(
            "❌ Батл не найден.",
            show_alert=True
        )
        return

    if battle[8] != 1:
        await callback.answer(
            "❌ Батл уже завершён.",
            show_alert=True
        )
        return

    if participant not in [1, 2]:
        await callback.answer(
            "❌ Неверный участник.",
            show_alert=True
        )
        return

    if amount not in [10, 25, 50, 100]:
        await callback.answer(
            "❌ Неверный пакет.",
            show_alert=True
        )
        return

    stars = get_boost_price(amount)

    if not stars or stars < 1:
        await callback.answer(
            "❌ Тариф временно недоступен.",
            show_alert=True
        )
        return

    payload = (
        f"boost:"
        f"{battle_id}:"
        f"{participant}:"
        f"{amount}:"
        f"{uuid.uuid4().hex[:16]}"
    )

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO boost_orders (
            payload,
            battle_id,
            user_id,
            participant,
            amount,
            stars,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
    """, (
        payload,
        battle_id,
        user_id,
        participant,
        amount,
        stars
    ))

    conn.commit()
    conn.close()

    try:

        await bot.send_invoice(
            chat_id=user_id,
            title=f"Буст +{amount} ⚡️",
            description=(
                f"Батл №{battle_id}. "
                f"Буст для участника №{participant}."
            ),
            payload=payload,
            currency="XTR",
            prices=[
                LabeledPrice(
                    label=f"+{amount} ⚡️",
                    amount=stars
                )
            ]
        )

        await callback.answer()

    except Exception as e:

        print(
            f"Ошибка создания invoice: {repr(e)}"
        )

        conn = db()
        cur = conn.cursor()

        cur.execute("""
            UPDATE boost_orders
            SET status = 'cancelled'
            WHERE payload = ?
        """, (payload,))

        conn.commit()
        conn.close()

        await callback.answer(
            "❌ Не удалось создать оплату.",
            show_alert=True
        )


# =========================================================
# PRE-CHECKOUT
# =========================================================

@dp.pre_checkout_query()
async def pre_checkout_handler(
    query: PreCheckoutQuery
):

    payload = query.invoice_payload

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            battle_id,
            user_id,
            participant,
            amount,
            stars,
            status
        FROM boost_orders
        WHERE payload = ?
    """, (payload,))

    order = cur.fetchone()
    conn.close()

    if not order:
        await query.answer(
            ok=False,
            error_message="Заказ не найден."
        )
        return

    battle_id = order[0]
    user_id = order[1]
    participant = order[2]
    amount = order[3]
    stars = order[4]
    status = order[5]

    if status != "pending":
        await query.answer(
            ok=False,
            error_message="Этот заказ уже обработан."
        )
        return

    battle = get_battle(battle_id)

    if not battle or battle[8] != 1:
        await query.answer(
            ok=False,
            error_message="Этот батл уже завершён."
        )
        return

    if query.from_user.id != user_id:
        await query.answer(
            ok=False,
            error_message="Этот счёт принадлежит другому пользователю."
        )
        return

    if query.currency != "XTR":
        await query.answer(
            ok=False,
            error_message="Неверная валюта оплаты."
        )
        return

    if query.total_amount != stars:
        await query.answer(
            ok=False,
            error_message="Цена заказа изменилась."
        )
        return

    await query.answer(ok=True)


# =========================================================
# SUCCESSFUL PAYMENT
# =========================================================

@dp.message(F.successful_payment)
async def successful_payment_handler(
    message: Message
):

    payment = message.successful_payment

    payload = payment.invoice_payload
    charge_id = payment.telegram_payment_charge_id

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            battle_id,
            user_id,
            participant,
            amount,
            stars,
            status
        FROM boost_orders
        WHERE payload = ?
    """, (payload,))

    order = cur.fetchone()

    if not order:
        conn.close()

        await message.answer(
            "⚠️ Оплата получена, но заказ не найден.\n"
            "Свяжись с администратором."
        )

        return

    battle_id = order[0]
    user_id = order[1]
    participant = order[2]
    amount = order[3]
    stars = order[4]
    status = order[5]

    if status == "paid":
        conn.close()

        await message.answer(
            "ℹ️ Этот платёж уже был обработан."
        )

        return

    cur.execute("""
        INSERT INTO boosts (
            battle_id,
            user_id,
            participant,
            amount,
            stars,
            charge_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        battle_id,
        user_id,
        participant,
        amount,
        stars,
        charge_id,
        datetime.utcnow().isoformat()
    ))

    cur.execute("""
        UPDATE boost_orders
        SET status = 'paid',
            charge_id = ?
        WHERE payload = ?
    """, (
        charge_id,
        payload
    ))

    conn.commit()
    conn.close()

    await message.answer(
        f"✅ <b>Буст успешно куплен!</b>\n\n"
        f"Батл: <b>№{battle_id}</b>\n"
        f"Участник: <b>№{participant}</b>\n"
        f"Добавлено: <b>+{amount} ⚡️</b>\n"
        f"Оплата: <b>{stars} ⭐</b>",
        parse_mode="HTML"
    )


# =========================================================
# BOOST STATISTICS
# =========================================================

def get_boosts(battle_id):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            participant,
            COALESCE(SUM(amount), 0)
        FROM boosts
        WHERE battle_id = ?
        GROUP BY participant
    """, (battle_id,))

    rows = cur.fetchall()

    conn.close()

    result = {
        1: 0,
        2: 0
    }

    for participant, amount in rows:
        result[participant] = amount

    return result


# =========================================================
# MAIN
# =========================================================

async def main():

    global BOT_USERNAME

    init_db()

    me = await bot.get_me()

    BOT_USERNAME = me.username

    print(
        f"Bot started: @{BOT_USERNAME}"
    )

    print(
        f"Channel: {CHANNEL}"
    )

    print(
        f"Admin ID: {ADMIN_ID}"
    )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
