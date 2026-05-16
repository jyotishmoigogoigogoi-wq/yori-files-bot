import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.exceptions import TelegramForbiddenError
from config import settings
from db import users_col, files_col
from models import User, VaultFile
import datetime

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

# Admin ID
ADMIN_ID = 7728424218

# Hardcoded channel link
CHANNEL_LINK = "https://t.me/YoriFederation"   # ← change if needed

# File size limit (50 MB)
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# ---------- /start (aesthetic + channel button) ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_data = await users_col.find_one({"tg_id": message.from_user.id})
    if not user_data:
        new_user = User(tg_id=message.from_user.id, username=message.from_user.username)
        await users_col.insert_one(new_user.model_dump())

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Open Yori Vault", web_app=WebAppInfo(url=settings.WEBAPP_URL))],
        [InlineKeyboardButton(text="📢 Join Channel", url=CHANNEL_LINK)]
    ])

    welcome_text = (
        "✨ ʏᴏʀɪ ᴠᴀᴜʟᴛ — sᴇᴄᴜʀᴇ ᴛᴇʟᴇɢʀᴀᴍ‑ɴᴀᴛɪᴠᴇ ᴄʟᴏᴜᴅ\n\n"
        "• sᴛᴏʀᴇ ғɪʟᴇs ɪɴ ғᴏʟᴅᴇʀs\n"
        "• 🔒 ᴘᴀssᴄᴏᴅᴇ ᴘʀᴏᴛᴇᴄᴛɪᴏɴ\n"
        "• ғᴀsᴛ, ᴘʀɪᴠᴀᴛᴇ, ʙᴜɪʟᴛ ᴏɴ ᴛɢ\n\n"
        "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        "ᴍᴀᴅᴇ ᴡɪᴛʜ 🧡 ʙʏ [ʏᴏʀɪ ғᴇᴅᴇʀᴀᴛɪᴏɴ](https://t.me/YoriFederation)"
    )
    await message.answer(welcome_text, reply_markup=markup, parse_mode="Markdown")

# ---------- /help ----------
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "📖 **how to use yori vault**\n\n"
        "• send any file here → saved to your vault root\n"
        "• open web app → manage folders, passcode, download\n"
        "• files are stored in a private telegram channel\n"
        "• passcode lock adds extra security\n\n"
        "❓ issues? contact @YoriFederation"
    )
    await message.answer(help_text, parse_mode="Markdown")

# ---------- /stats (admin only) ----------
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Admin only command.")
        return
    total_users = await users_col.count_documents({})
    await message.answer(f"📊 **vault stats**\n\n👥 Total users: `{total_users}`", parse_mode="Markdown")

# ---------- /broadcast (admin only) ----------
broadcast_data = {}

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Admin only command.")
        return

    if not message.reply_to_message:
        await message.answer("📌 Reply to a message (text/photo/video/document) with /broadcast")
        return

    original = message.reply_to_message
    broadcast_data[message.from_user.id] = original

    preview_text = "📢 **preview of broadcast**\n\n"
    if original.text:
        preview_text += original.text
    elif original.caption:
        preview_text += original.caption
    else:
        preview_text += "(media without caption)"

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Send", callback_data="broadcast_send"),
         InlineKeyboardButton(text="✏️ Edit", callback_data="broadcast_edit")]
    ])

    if original.content_type in ["photo", "video", "document"]:
        if original.content_type == "photo":
            await original.answer_photo(photo=original.photo[-1].file_id, caption=preview_text, reply_markup=markup, parse_mode="Markdown")
        elif original.content_type == "video":
            await original.answer_video(video=original.video.file_id, caption=preview_text, reply_markup=markup, parse_mode="Markdown")
        elif original.content_type == "document":
            await original.answer_document(document=original.document.file_id, caption=preview_text, reply_markup=markup, parse_mode="Markdown")
    else:
        await message.answer(preview_text, reply_markup=markup, parse_mode="Markdown")

@dp.callback_query(lambda c: c.data in ["broadcast_send", "broadcast_edit"])
async def broadcast_callback(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Admin only", show_alert=True)
        return

    original_msg = broadcast_data.get(callback.from_user.id)
    if not original_msg:
        await callback.answer("No broadcast data. Send /broadcast again.", show_alert=True)
        return

    if callback.data == "broadcast_edit":
        await callback.answer("Cancelled. Edit your message and reply with /broadcast again.")
        await callback.message.delete()
        broadcast_data.pop(callback.from_user.id, None)
        return

    await callback.answer("Broadcasting started...")
    await callback.message.edit_reply_markup(reply_markup=None)

    all_users = await users_col.find().to_list(None)
    success = 0
    failed = 0

    status_msg = await callback.message.answer("🔄 Broadcasting in progress... 0%")

    for idx, user_doc in enumerate(all_users):
        user_id = user_doc["tg_id"]
        try:
            if original_msg.content_type == "text":
                await bot.send_message(user_id, original_msg.text, parse_mode="Markdown" if original_msg.text else None)
            elif original_msg.content_type == "photo":
                await bot.send_photo(user_id, original_msg.photo[-1].file_id, caption=original_msg.caption, parse_mode="Markdown" if original_msg.caption else None)
            elif original_msg.content_type == "video":
                await bot.send_video(user_id, original_msg.video.file_id, caption=original_msg.caption, parse_mode="Markdown" if original_msg.caption else None)
            elif original_msg.content_type == "document":
                await bot.send_document(user_id, original_msg.document.file_id, caption=original_msg.caption, parse_mode="Markdown" if original_msg.caption else None)
            else:
                await original_msg.forward(user_id)
            success += 1
        except TelegramForbiddenError:
            failed += 1
        except Exception:
            failed += 1

        if (idx + 1) % 10 == 0 or (idx + 1) == len(all_users):
            percent = int((idx + 1) / len(all_users) * 100)
            await status_msg.edit_text(f"🔄 Broadcasting... {percent}%\n✅ {success} | ❌ {failed}")

    await status_msg.edit_text(f"📢 **broadcast finished**\n\n✅ Sent to `{success}` users\n❌ Failed (blocked/invalid): `{failed}`", parse_mode="Markdown")
    broadcast_data.pop(callback.from_user.id, None)

# ---------- File Upload Handler (with size limit) ----------
@dp.message(F.document | F.photo | F.video | F.audio)
async def handle_uploads(message: types.Message):
    user_data = await users_col.find_one({"tg_id": message.from_user.id})
    if not user_data:
        await message.answer("Please /start the bot first.")
        return

    # Determine file size before forwarding
    size = 0
    if message.document:
        size = message.document.file_size
    elif message.photo:
        size = message.photo[-1].file_size
    elif message.video:
        size = message.video.file_size
    elif message.audio:
        size = message.audio.file_size

    # Check size limit
    if size > MAX_FILE_SIZE_BYTES:
        await message.reply(f"❌ File too large. Maximum size is {MAX_FILE_SIZE_MB} MB. Your file is {size / (1024*1024):.1f} MB.")
        return

    # Forward to storage channel
    copied_msg = await message.copy_to(chat_id=settings.STORAGE_CHANNEL_ID)
    
    # Extract file metadata
    file_id = None
    file_unique_id = None
    filename = "Untitled"
    mime_type = "application/octet-stream"

    if message.document:
        file_id = message.document.file_id
        file_unique_id = message.document.file_unique_id
        filename = message.document.file_name or "document"
        mime_type = message.document.mime_type
    elif message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        file_unique_id = photo.file_unique_id
        filename = f"photo_{message.message_id}.jpg"
        mime_type = "image/jpeg"
    elif message.video:
        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
        filename = message.video.file_name or f"video_{message.message_id}.mp4"
        mime_type = message.video.mime_type
    elif message.audio:
        file_id = message.audio.file_id
        file_unique_id = message.audio.file_unique_id
        filename = message.audio.file_name or f"audio_{message.message_id}.mp3"
        mime_type = message.audio.mime_type

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
