import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: Message):
    print(f"START: {message.from_user.id}", flush=True)

    await message.answer(
        "✅ Бот работает.\n\n"
        "Теперь отправь мне фотографию."
    )


@dp.message(F.photo)
async def photo(message: Message):
    print(
        f"PHOTO RECEIVED: user={message.from_user.id}",
        flush=True
    )

    photo_id = message.photo[-1].file_id

    print(
        f"PHOTO ID: {photo_id}",
        flush=True
    )

    await message.answer(
        "📸 ФОТО ПОЛУЧЕНО!\n\n"
        f"Размеров фото: {len(message.photo)}\n"
        f"ID: {photo_id}"
    )


@dp.message()
async def any_message(message: Message):
    print(
        f"MESSAGE RECEIVED: type={message.content_type}",
        flush=True
    )

    await message.answer(
        f"Я получил сообщение типа: {message.content_type}"
    )


async def main():
    print("==============================", flush=True)
    print("BOT STARTING", flush=True)
    print(f"TOKEN EXISTS: {bool(TOKEN)}", flush=True)
    print("==============================", flush=True)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
