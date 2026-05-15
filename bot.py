from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from config import settings
from db import users_col, files_col
from models import User, VaultFile
import datetime

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_data = await users_col.find_one({"tg_id": message.from_user.id})
    if not user_data:
        new_user = User(tg_id=message.from_user.id, username=message.from_user.username)
        await users_col.insert_one(new_user.model_dump())

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☁️ Open Yori Vault", web_app=WebAppInfo(url=settings.WEBAPP_URL))]
    ])
    
    welcome_text = (
        "🛡 **Welcome to Yori Federation Vault**\n\n"
        "Your secure, private Telegram-native cloud storage.\n"
        "Send files here to save them to your root directory, or open the app to manage your vault.\n\n"
        "*(Made by Yori Federation - https://t.me/YoriFederation)*"
    )
    await message.answer(welcome_text, reply_markup=markup, parse_mode="Markdown")

@dp.message(F.document | F.photo | F.video | F.audio)
async def handle_uploads(message: types.Message):
    # Verify user exists
    user_data = await users_col.find_one({"tg_id": message.from_user.id})
    if not user_data:
        await message.answer("Please /start the bot first.")
        return

    # Forward to storage channel
    copied_msg = await message.copy_to(chat_id=settings.STORAGE_CHANNEL_ID)
    
    # Extract file metadata
    file_id = None
    file_unique_id = None
    filename = "Untitled"
    mime_type = "application/octet-stream"
    size = 0

    if message.document:
        file_id = message.document.file_id
        file_unique_id = message.document.file_unique_id
        filename = message.document.file_name or "document"
        mime_type = message.document.mime_type
        size = message.document.file_size
    elif message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_unique_id = photo.file_unique_id
        filename = f"photo_{message.message_id}.jpg"
        mime_type = "image/jpeg"
        size = photo.file_size
    elif message.video:
        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
        filename = message.video.file_name or f"video_{message.message_id}.mp4"
        mime_type = message.video.mime_type
        size = message.video.file_size
    elif message.audio:
        file_id = message.audio.file_id
        file_unique_id = message.audio.file_unique_id
        filename = message.audio.file_name or f"audio_{message.message_id}.mp3"
        mime_type = message.audio.mime_type
        size = message.audio.file_size

    new_file = VaultFile(
        owner_id=message.from_user.id,
        folder_id=None,
        filename=filename,
        mime_type=mime_type,
        size=size,
        file_id=file_id,
        file_unique_id=file_unique_id,
        message_id=copied_msg.message_id
    )
    await files_col.insert_one(new_file.model_dump())
    await message.reply(f"✅ Saved `{filename}` to your Vault Root.\nOpen the Web App to manage it.", parse_mode="Markdown")
