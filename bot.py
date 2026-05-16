from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, CallbackQuery
from config import settings
from db import users_col, files_col
from models import User, VaultFile
import asyncio

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()

ADMIN_ID = 7728424218

# --- 1. AESTHETIC START COMMAND ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_data = await users_col.find_one({"tg_id": message.from_user.id})
    if not user_data:
        new_user = User(tg_id=message.from_user.id, username=message.from_user.username)
        await users_col.insert_one(new_user.model_dump())

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☁️ ᴏᴘᴇɴ ᴠᴀᴜʟᴛ", web_app=WebAppInfo(url=settings.WEBAPP_URL))],
        [InlineKeyboardButton(text="📢 ᴏғғɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ", url="https://t.me/YoriFederation")]
    ])
    
    welcome_text = (
        "<b>ʏᴏʀɪ ꜰᴇᴅᴇʀᴀᴛɪᴏɴ ᴠᴀᴜʟᴛ</b>\n\n"
        "sᴇᴄᴜʀᴇ ‧ ᴘʀɪᴠᴀᴛᴇ ‧ ɴᴀᴛɪᴠᴇ\n\n"
        "<i>ʏᴏᴜʀ ᴘᴇʀsᴏɴᴀʟ ᴄʟᴏᴜᴅ ɪɴsɪᴅᴇ ᴛᴇʟᴇɢʀᴀᴍ. "
        "sᴇɴᴅ ᴀɴʏ ғɪʟᴇ ʜᴇʀᴇ ᴛᴏ sᴀᴠᴇ ɪᴛ, ᴏʀ ᴏᴘᴇɴ ᴛʜᴇ ᴠᴀᴜʟᴛ ᴛᴏ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ᴅᴀᴛᴀ.</i>"
    )
    await message.answer(welcome_text, reply_markup=markup, parse_mode="HTML")

# --- 2. HELP COMMAND ---
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "<b>🛡 ʜᴏᴡ ᴛᴏ ᴜsᴇ ʏᴏʀɪ ᴠᴀᴜʟᴛ</b>\n\n"
        "<b>1. ᴜᴘʟᴏᴀᴅɪɴɢ ғɪʟᴇs:</b>\n"
        "sᴇɴᴅ ᴀɴʏ ᴘʜᴏᴛᴏ, ᴠɪᴅᴇᴏ, ᴏʀ ᴅᴏᴄᴜᴍᴇɴᴛ ᴅɪʀᴇᴄᴛʟʏ ᴛᴏ ᴛʜɪs ᴄʜᴀᴛ. ɪᴛ ᴡɪʟʟ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ sᴀᴠᴇ ᴛᴏ ʏᴏᴜʀ ʀᴏᴏᴛ ғᴏʟᴅᴇʀ.\n\n"
        "<b>2. ᴍᴀɴᴀɢɪɴɢ ғɪʟᴇs:</b>\n"
        "ᴄʟɪᴄᴋ 'ᴏᴘᴇɴ ᴠᴀᴜʟᴛ' ᴛᴏ ᴄʀᴇᴀᴛᴇ ғᴏʟᴅᴇʀs, ᴍᴏᴠᴇ ғɪʟᴇs, ᴏʀ ᴅᴏᴡɴʟᴏᴀᴅ ᴛʜᴇᴍ.\n\n"
        "<b>3. sᴇᴄᴜʀɪᴛʏ:</b>\n"
        "ʏᴏᴜ ᴄᴀɴ sᴇᴛ ᴀ ᴘᴀssᴄᴏᴅᴇ ɪɴsɪᴅᴇ ᴛʜᴇ ᴀᴘᴘ. ᴀʟʟ ғɪʟᴇs ᴀʀᴇ ᴘʀɪᴠᴀᴛᴇ."
    )
    await message.answer(help_text, parse_mode="HTML")

# --- 3. ADMIN STATS ---
@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    total_users = await users_col.count_documents({})
    total_files = await files_col.count_documents({})
    
    stats_text = (
        "📊 <b>ᴠᴀᴜʟᴛ sᴛᴀᴛɪsᴛɪᴄs</b>\n\n"
        f"👥 <b>ᴛᴏᴛᴀʟ ᴜsᴇʀs:</b> {total_users}\n"
        f"📁 <b>ᴛᴏᴛᴀʟ ғɪʟᴇs sᴀᴠᴇᴅ:</b> {total_files}"
    )
    await message.answer(stats_text, parse_mode="HTML")

# --- 4. ADMIN BROADCAST SYSTEM ---
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    if not message.reply_to_message:
        await message.answer("⚠️ Please reply to the message you want to broadcast with /broadcast")
        return

    # Send preview
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Send", callback_data=f"bcast_send_{message.reply_to_message.message_id}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="bcast_cancel")
        ]
    ])
    
    await message.answer("📢 <b>BROADCAST PREVIEW</b>\n\nIs this the message you want to send?", reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("bcast_"))
async def handle_broadcast_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Unauthorized", show_alert=True)
        return

    action = call.data.split("_")[1]
    
    if action == "cancel":
        await call.message.edit_text("❌ Broadcast cancelled.")
        return
        
    if action == "send":
        msg_id = int(call.data.split("_")[2])
        await call.message.edit_text("⏳ Broadcasting to all users... Please wait.")
        
        success = 0
        failed = 0
        users = await users_col.find({}).to_list(None)
        
        for u in users:
            try:
                await bot.copy_message(
                    chat_id=u["tg_id"],
                    from_chat_id=call.message.chat.id,
                    message_id=msg_id
                )
                success += 1
                await asyncio.sleep(0.05) # Prevent Telegram flood limits
            except Exception:
                failed += 1
                
        report = (
            "✅ <b>BROADCAST COMPLETE</b>\n\n"
            f"🟢 <b>Sent successfully:</b> {success}\n"
            f"🔴 <b>Blocked/Failed:</b> {failed}"
        )
        await call.message.edit_text(report, parse_mode="HTML")

# --- 5. UPLOAD HANDLER ---
@dp.message(F.document | F.photo | F.video | F.audio)
async def handle_uploads(message: types.Message):
    user_data = await users_col.find_one({"tg_id": message.from_user.id})
    if not user_data:
        await message.answer("Please /start the bot first.")
        return

    # Check size (Max 40MB from bot directly)
    size = 0
    if message.document: size = message.document.file_size
    elif message.photo: size = message.photo[-1].file_size
    elif message.video: size = message.video.file_size
    elif message.audio: size = message.audio.file_size
    
    if size and size > 40 * 1024 * 1024:
        await message.answer("❌ File exceeds 40MB limit.")
        return

    copied_msg = await message.copy_to(chat_id=settings.STORAGE_CHANNEL_ID)
    
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
    await message.reply(f"✅ <b>sᴀᴠᴇᴅ:</b> <code>{filename}</code>\n<i>ᴏᴘᴇɴ ᴛʜᴇ ᴠᴀᴜʟᴛ ᴛᴏ ᴠɪᴇᴡ.</i>", parse_mode="HTML")
