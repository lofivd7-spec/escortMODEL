import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

bot = Bot(token=TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start_handler(message: Message):
    print(
        f"\nSTART: user={message.from_user.id}",
        flush=True
    )

    await message.answer(
        "Бот работает.\n\n"
        "Теперь отправь мне обычную фотографию."
    )


@dp.message()
async def all_messages_handler(message: Message):

    print("\n==============================", flush=True)
    print(
        f"MESSAGE RECEIVED",
        flush=True
    )
    print(
        f"user_id: {message.from_user.id}",
        flush=True
    )
    print(
        f"content_type: {message.content_type}",
        flush=True
    )
    print(
        f"photo: {message.photo}",
        flush=True
    )
    print(
        f"text: {message.text}",
        flush=True
    )
    print("==============================\n", flush=True)

    if message.photo:

        photo = message.photo[-1]

        print(
            f"PHOTO FOUND!",
            flush=True
        )

        print(
            f"file_id = {photo.file_id}",
            flush=True
        )

        print(
            f"width = {photo.width}",
            flush=True
        )

        print(
            f"height = {photo.height}",
            flush=True
        )

        await message.answer(
            "✅ ФОТО ПОЛУЧЕНО!\n\n"
            f"file_id:\n{photo.file_id}"
        )

        return

    await message.answer(
        f"Я получил сообщение.\n"
        f"Тип: {message.content_type}"
    )


async def main():

    print("==============================", flush=True)
    print("BOT STARTING", flush=True)
    print(f"TOKEN EXISTS: {bool(TOKEN)}", flush=True)
    print("==============================", flush=True)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
