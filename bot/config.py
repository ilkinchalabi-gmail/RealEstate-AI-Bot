import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# ── Groq / AI ─────────────────────────────────────────────
GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
GROQ_MODEL         = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Başlanğıc yoxlama ────────────────────────────────────
_required = {"TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN, "GROQ_API_KEY": GROQ_API_KEY}
_missing = [k for k, v in _required.items() if not v]
if _missing:
    print(f"❌ XƏTA: Bu env var-lar təyin edilməyib: {', '.join(_missing)}")
    print("   Railway → Variables bölməsindən əlavə edin.")
    sys.exit(1)

# ── Google Sheets ─────────────────────────────────────────
GOOGLE_SHEET_ID        = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "../market-cloud-api-5fbec00418a6.json")
KNOWLEDGE_SHEET_NAME   = os.getenv("KNOWLEDGE_SHEET_NAME", "Bilgi")
LEADS_SHEET_NAME       = os.getenv("LEADS_SHEET_NAME", "Sheet1")
# ── Sheets Timeout Settings ───────────────────────────────
SHEETS_TIMEOUT         = int(os.getenv("SHEETS_TIMEOUT", "10"))
SHEETS_RETRY_ATTEMPTS  = int(os.getenv("SHEETS_RETRY_ATTEMPTS", "3"))
SHEETS_RETRY_DELAY     = int(os.getenv("SHEETS_RETRY_DELAY", "2"))
SHEETS_CLIENT_TIMEOUT  = int(os.getenv("SHEETS_CLIENT_TIMEOUT", "20"))
# ── Bot Ayarları ──────────────────────────────────────────
BOT_LANGUAGE   = os.getenv("BOT_LANGUAGE", "az")
MEMORY_WINDOW  = int(os.getenv("MEMORY_WINDOW", "20"))

# ── CRM (hazırda deaktiv) ─────────────────────────────────
CRM_ENABLED   = os.getenv("CRM_ENABLED", "false").lower() == "true"
CRM_ENDPOINT  = os.getenv("CRM_ENDPOINT", "")
CRM_API_KEY   = os.getenv("CRM_API_KEY", "")
