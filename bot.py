import os
import re
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.request import HTTPXRequest

# 🎯 Qabul qilinadigan video platformalar regexi
VIDEO_LINK_REGEX = re.compile(
    r"(https?://(?:www\.)?"
    r"(youtube\.com|youtu\.be|facebook\.com|fb\.watch|instagram\.com|tiktok\.com)"
    r"/[^\s]+)"
)

# 🧾 Saqlanadigan linklar (user_id + message_id → url)
user_video_links = {}

# 📥 Video yuklab olish funksiyasi
def download_video(url, filename):
    ydl_opts = {
        'outtmpl': filename,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4',
        'quiet': True,
        'max_filesize': 50 * 1024 * 1024,
        'merge_output_format': 'mp4'
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except yt_dlp.utils.DownloadError as e:
        print(f"[Xato] Video yuklab bo'lmadi: {str(e)}")
        return False
    except Exception as e:
        print(f"[Kritik Xato] {type(e).__name__}: {str(e)}")
        return False

# 🎵 MP3 yuklab olish funksiyasi
def download_audio(url, filename):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': filename,
        'quiet': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'max_filesize': 50 * 1024 * 1024,
    }
    
    # Linux uchun ffmpeg tekshiruvi
    if os.name == 'posix':
        ydl_opts['ffmpeg_location'] = '/usr/bin/ffmpeg'

    try:
        print(f"[INFO] MP3 yuklash boshlandi: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        mp3_filename = f"{filename}.mp3"
        if os.path.exists(mp3_filename):
            print(f"[OK] MP3 fayl tayyor: {mp3_filename}")
            return mp3_filename
        else:
            print(f"[Xato] MP3 fayli yaratilmadi: {mp3_filename}")
            return None
    except yt_dlp.utils.DownloadError as e:
        print(f"[Xato] Audio yuklab bo'lmadi: {str(e)}")
        return None
    except Exception as e:
        print(f"[Kritik Xato] {type(e).__name__}: {str(e)}")
        return None

# 🧾 Xabarni qayta ishlash
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text or ""
    match = VIDEO_LINK_REGEX.search(text)

    if match:
        url = match.group(1)
        user = update.message.from_user
        message_id = update.message.message_id
        chat_id = update.message.chat_id

        if user.username:
            sender_name = f"@{user.username}"
        else:
            sender_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

        # Xabarni yuborish
        loading_msg = await update.message.reply_text("📥 Video yuklanmoqda...")

        video_filename = f"downloads/video_{chat_id}_{message_id}"
        success = download_video(url, video_filename)

        if success:
            actual_filename = f"{video_filename}.mp4"
            if not os.path.exists(actual_filename):
                await loading_msg.edit_text("⚠️ Video fayli topilmadi")
                return

            filesize = os.path.getsize(actual_filename)
            if filesize > 50 * 1024 * 1024:
                await loading_msg.edit_text("⚠️ Video 50MB dan katta. Yuborib bo'lmaydi.")
                os.remove(actual_filename)
                return

            caption = f"🎬 Yuklandi\n👤 {sender_name}"
            try:
                with open(actual_filename, 'rb') as video_file:
                    await update.message.reply_video(
                        video=video_file,
                        caption=caption,
                        supports_streaming=True
                    )
                await loading_msg.delete()
            except Exception as e:
                await loading_msg.edit_text(f"⚠️ Xato yuz berdi: {str(e)}")
            finally:
                if os.path.exists(actual_filename):
                    os.remove(actual_filename)

            # 🔘 Inline tugma: MP3 yuklash
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎵 MP3 yuklash", callback_data=f"get_mp3|{user.id}|{message_id}")]
            ])
            await update.message.reply_text("🎧 Agar faqat musiqa kerak bo'lsa:", reply_markup=keyboard)

            # 🔐 Linkni eslab qolamiz
            user_video_links[(user.id, message_id)] = url

            # ✅ Asl xabarni o'chirish (faqat bot admin bo'lsa)
            try:
                bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
                # Agar bot administrator bo'lsa
                if bot_member.status == "administrator" and hasattr(bot_member, 'can_delete_messages'):
                    if bot_member.can_delete_messages:
                        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                # Agar bot guruh egasi bo'lsa (creator)
                elif bot_member.status == "creator":
                    await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception as e:
                print(f"[Ogohlantirish] Xabarni o'chirib bo'lmadi: {str(e)}")
        else:
            await loading_msg.edit_text("⚠️ Video yuklab bo'lmadi. Iltimos, boshqa link yuboring.")
    else:
        pass

# 🔘 Inline tugma: MP3 yuklab yuborish
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("get_mp3"):
        _, user_id, msg_id = data.split("|")
        key = (int(user_id), int(msg_id))

        url = user_video_links.get(key)
        if not url:
            await query.edit_message_text("❌ Audio uchun havola topilmadi.")
            return

        msg = await query.edit_message_text("🎵 MP3 fayl tayyorlanmoqda...")

        audio_filename = f"downloads/audio_{query.message.chat_id}_{msg_id}"
        result_file = download_audio(url, audio_filename)

        if result_file and os.path.exists(result_file):
            filesize = os.path.getsize(result_file)
            print(f"[INFO] MP3 hajmi: {filesize / (1024 * 1024):.2f} MB")

            if filesize > 50 * 1024 * 1024:
                await msg.edit_text("⚠️ MP3 50MB dan katta. Yuborib bo'lmaydi.")
                os.remove(result_file)
                return

            try:
                with open(result_file, 'rb') as audio_file:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=audio_file,
                        caption="🎧 MP3 yuklandi.",
                        title="Yuklangan musiqa",
                        performer="Telegram Bot"
                    )
                await msg.delete()
            except Exception as e:
                print(f"[Xato] MP3 yuborilmadi: {str(e)}")
                await msg.edit_text(f"❌ MP3 yuborilmadi: {str(e)}")
            finally:
                if os.path.exists(result_file):
                    os.remove(result_file)
        else:
            await msg.edit_text("❌ MP3 yuklab bo'lmadi. Iltimos, qayta urinib ko'ring.")

# 🚀 Botni ishga tushirish
def main():
    BOT_TOKEN = "8086222828:AAFm5Lg5CPghCdo_DTVwy88EuDUJFqfBtIk"

    # Fayllar uchun papka yaratish
    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    app = ApplicationBuilder().token(BOT_TOKEN).request(
        HTTPXRequest(
            read_timeout=120,
            connect_timeout=60,
            write_timeout=120
        )
    ).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("🤖 Bot ishga tushdi...")
    app.run_polling()

if __name__ == '__main__':
    main()
