"""
main.py — Telegram Bot əsas faylı.

Komandalar:
  /start     → Xoş gəldin mesajı
  /sil       → Söhbəti sıfırla
  /lead      → Cari lead məlumatını göstər
  /kb        → Knowledge Base-ə məlumat əlavə et (admin)
  /help      → Kömək mətni
"""

import asyncio
import logging
import os
from datetime import datetime

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatAction

from config import TELEGRAM_BOT_TOKEN
from agent import get_ai_response
from memory import clear_history, get_lead
from sync import sync_leads_to_sheets
from sheets import add_knowledge_entry

# ── Logging ───────────────────────────────────────────────────
os.makedirs(os.path.join(os.path.dirname(__file__), "data"), exist_ok=True)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "data", "bot.log"),
            encoding="utf-8"
        ),
    ]
)
logger = logging.getLogger(__name__)

# ── Global sync task üçün holder ──────────────────────────────
_sync_task: asyncio.Task | None = None

# ── KB Conversation states ────────────────────────────────────
KB_SUAL, KB_CAVAB, KB_KATEQORIYA = range(3)

# ── Helpers ───────────────────────────────────────────────────
def _user_id(update: Update) -> str:
    return str(update.effective_user.id)

def _user_name(update: Update) -> str:
    u = update.effective_user
    parts = [u.first_name or "", u.last_name or ""]
    return " ".join(p for p in parts if p).strip() or u.username or "İsimsiz"


# ── Komandalar ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "Qonaq"
    await update.message.reply_text(
        f"👋 Salam, {name}!\n\n"
        "Mən İlkin bəyin emlak köməkçisiyəm. Dubai və ətraf ərazilərdə "
        "mülk almaq, satmaq, icarə və ya investisiya haqqında istənilən "
        "sualınızı verə bilərsiniz.\n\n"
        "💬 Sadəcə mesaj yazın, sizə kömək edim!\n"
        "🌍 You can also write in English, Русский, Türkçe — I'll respond in your language."
    )
    logger.info(f"[Start] User {_user_id(update)} ({_user_name(update)}) botu açdı.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏠 *Emlak AI Köməkçisi*\n\n"
        "Edə bildiklərim:\n"
        "• Dubai emlak bazarı haqqında məlumat\n"
        "• Mülk qiymətləri və rayon tövsiyəsi\n"
        "• Alqı-satqı və icarə prosesi izahı\n"
        "• İnvestisiya məsləhəti\n\n"
        "📋 *Komandalar:*\n"
        "/start — Yenidən başla\n"
        "/sil — Söhbəti təmizlə\n"
        "/lead — Məlumatlarımı göstər\n"
        "/kb — Bilgi bazasına məlumat əlavə et\n"
        "/help — Bu mesaj\n\n"
        "🌍 I speak: AZ • EN • TR • RU • AR",
        parse_mode="Markdown"
    )


async def cmd_sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(_user_id(update))
    await update.message.reply_text(
        "🗑️ Söhbət tarixçəniz silindi. Yenidən başlaya bilərik!"
    )


async def cmd_lead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lead = get_lead(_user_id(update))
    if not lead:
        await update.message.reply_text("📋 Hələ heç bir məlumatınız qeydə alınmayıb.")
        return

    text = (
        f"📋 *Sizin Məlumatlarınız:*\n\n"
        f"👤 Ad: {lead.get('ad') or '—'} {lead.get('soyad') or ''}\n"
        f"📞 Telefon: {lead.get('telefon') or '—'}\n"
        f"📧 Email: {lead.get('email') or '—'}\n"
        f"💰 Büdcə: {lead.get('budce') or '—'}\n"
        f"📍 Maraq yeri: {lead.get('maraq_yerleri') or '—'}\n"
        f"🏗️ Layihə: {lead.get('proyekt') or '—'}\n"
        f"🌡️ Lead Skoru: {lead.get('lead_skoru') or '—'}\n"
        f"📊 Durum: {lead.get('durum') or 'Yeni'}\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── KB (Knowledge Base) 3-addımlı söhbət ────────────────────

async def cmd_kb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Knowledge Base-ə məlumat əlavə etmə prosesini başlat."""
    await update.message.reply_text(
        "📚 *Bilgi Bazasına Məlumat Əlavə Et*\n\n"
        "Addım 1/3: Sual və ya mövzunu yazın.\n"
        "Məsələn: _Dubai-da mülk almaq üçün minimum büdcə nə qədərdir?_\n\n"
        "Ləğv etmək üçün /ləğvet yazın.",
        parse_mode="Markdown"
    )
    return KB_SUAL


async def kb_get_sual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["kb_sual"] = update.message.text
    await update.message.reply_text(
        "✅ Sual qeyd edildi.\n\n"
        "Addım 2/3: İndi cavabı yazın:"
    )
    return KB_CAVAB


async def kb_get_cavab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["kb_cavab"] = update.message.text
    await update.message.reply_text(
        "✅ Cavab qeyd edildi.\n\n"
        "Addım 3/3: Kateqoriya seçin (yazın):\n"
        "• Qiymət\n• Rayon\n• Layihə\n• Proses\n• İnvestisiya\n• Ümumi"
    )
    return KB_KATEQORIYA


async def kb_get_kateqoriya(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sual = context.user_data.get("kb_sual", "")
    cavab = context.user_data.get("kb_cavab", "")
    kateqoriya = update.message.text

    try:
        success = add_knowledge_entry(sual, cavab, kateqoriya)
        if success:
            await update.message.reply_text(
                f"✅ *Bilgi bazasına əlavə edildi!*\n\n"
                f"❓ Sual: {sual[:60]}...\n"
                f"📝 Kateqoriya: {kateqoriya}\n\n"
                f"Bot bu məlumatdan dərhal istifadə edəcək.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Xəta baş verdi. Yenidən cəhd edin.")
    except Exception as e:
        logger.error(f"[KB] Əlavə xətası: {e}")
        await update.message.reply_text(f"❌ Xəta: {str(e)[:100]}")

    context.user_data.clear()
    return ConversationHandler.END


async def kb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Ləğv edildi.")
    return ConversationHandler.END


# ── Əsas Mesaj Handler ────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = _user_id(update)
    user_name = _user_name(update)
    user_text = update.message.text.strip()

    if not user_text:
        return

    logger.info(f"[MSG] {user_id} ({user_name}): {user_text[:80]}")

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )

    try:
        answer, intent = get_ai_response(user_id, user_name, user_text)
        logger.info(f"[INTENT] {user_id}: {intent}")
        await update.message.reply_text(answer)
    except Exception as e:
        logger.error(f"[handle_message] Xəta: {e}")
        await update.message.reply_text(
            "😔 Bağışlayın, bir problem yarandı. Zəhmət olmasa bir az sonra yenidən cəhd edin."
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🖼️ Şəkli gördüm! Lakin hazırda yalnız mətn mesajlarını işləyirəm. "
        "Sualınızı yazın, kömək edim."
    )


# ── Bot startup ───────────────────────────────────────────────

async def post_init(application: Application):
    """Bot başladıqda komandaları qurun və sync task-ı başladın."""
    global _sync_task
    
    commands = [
        BotCommand("start",  "Botu başlat"),
        BotCommand("help",   "Kömək"),
        BotCommand("sil",    "Söhbəti sil"),
        BotCommand("lead",   "Məlumatlarımı göstər"),
        BotCommand("kb",     "Bilgi bazasına məlumat əlavə et"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("✅ Bot komandaları qeydiyyatdan keçdi.")
    
    # Sync task-ı yaratın
    _sync_task = asyncio.create_task(sync_leads_to_sheets(interval_seconds=60))
    logger.info("✅ Google Sheets sync taskı başladı (timeout qorunmuş).")


async def shutdown(application: Application):
    """Bot bağlandıqda sync task-ı təmiz bir şəkildə ləğv edin."""
    global _sync_task
    
    logger.info("🛑 Bot bağlanır, sync task-ı ləğv edilir...")
    if _sync_task and not _sync_task.done():
        _sync_task.cancel()
        try:
            await _sync_task
        except asyncio.CancelledError:
            logger.info("✅ Sync task ləğv edildi.")
    logger.info("🛑 Bot bağlandı.")


# ── Main ──────────────────────────────────────────────────────

def main():
    logger.info("🚀 Real Estate AI Bot başlayır...")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # KB ConversationHandler
    kb_handler = ConversationHandler(
        entry_points=[CommandHandler("kb", cmd_kb)],
        states={
            KB_SUAL:      [MessageHandler(filters.TEXT & ~filters.COMMAND, kb_get_sual)],
            KB_CAVAB:     [MessageHandler(filters.TEXT & ~filters.COMMAND, kb_get_cavab)],
            KB_KATEQORIYA:[MessageHandler(filters.TEXT & ~filters.COMMAND, kb_get_kateqoriya)],
        },
        fallbacks=[CommandHandler("legvet", kb_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("sil",   cmd_sil))
    app.add_handler(CommandHandler("lead",  cmd_lead))
    app.add_handler(kb_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("✅ Bot polling rejiminə keçdi. Dayandırmaq üçün Ctrl+C.")
    
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("⚠️ Keyboard interrupt qəbul edildi.")
    finally:
        logger.info("🛑 Bot bağlanır.")


if __name__ == "__main__":
    main()
