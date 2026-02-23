"""
sheets.py — Google Sheets inteqrasiyası.

Funksiyalar:
1. get_knowledge_base()     → Bilgi Bankasını oxu
2. add_knowledge_entry()    → Bilgi Bankasına yeni sıra əlavə et
3. append_lead_to_sheet()   → Lead-i Sheets-ə yaz
4. update_lead_in_sheet()   → Mövcud lead-i yenilə
"""

import gspread
import os
import socket
from datetime import datetime
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_PATH, GOOGLE_SHEET_ID, KNOWLEDGE_SHEET_NAME, LEADS_SHEET_NAME, SHEETS_CLIENT_TIMEOUT

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_creds_path = os.path.join(os.path.dirname(__file__), GOOGLE_CREDENTIALS_PATH)


def _get_client() -> gspread.Client:
    """Initialize gspread client with timeout settings."""
    socket.setdefaulttimeout(SHEETS_CLIENT_TIMEOUT)
    creds = Credentials.from_service_account_file(_creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_or_create_worksheet(sheet, name: str, headers: list) -> gspread.Worksheet:
    """Sheet varsa qaytar, yoxdursa yarat + header əlavə et."""
    try:
        ws = sheet.worksheet(name)
        # Header yoxdursa əlavə et
        existing = ws.get_all_values()
        if not existing:
            ws.append_row(headers)
        return ws
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=name, rows=1000, cols=20)
        ws.append_row(headers)
        return ws


# ─────────────────────────────────────────────────────────────
# BİLGİ BANKASI
# ─────────────────────────────────────────────────────────────

_kb_cache: str = ""
_kb_last_loaded: datetime | None = None
KB_CACHE_MINUTES = 5

KNOWLEDGE_HEADERS = ["Sual/Mövzu", "Cavab", "Kateqoriya", "Əlavə tarixi"]


def get_knowledge_base() -> str:
    """
    Bilgi Bankası sheetini oxu və string kimi qaytar.
    5 dəqiqəlik cache var.
    """
    global _kb_cache, _kb_last_loaded

    now = datetime.now()
    if _kb_last_loaded and (now - _kb_last_loaded).seconds < KB_CACHE_MINUTES * 60 and _kb_cache:
        return _kb_cache

    try:
        client = _get_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = _get_or_create_worksheet(sheet, KNOWLEDGE_SHEET_NAME, KNOWLEDGE_HEADERS)

        rows = ws.get_all_values()
        if len(rows) <= 1:
            _kb_cache = ""
            _kb_last_loaded = now
            return ""

        headers = rows[0]
        lines = []
        for row in rows[1:]:
            if any(cell.strip() for cell in row):
                entry = " | ".join(
                    f"{h}: {v}" for h, v in zip(headers, row) if v.strip()
                )
                lines.append(entry)

        _kb_cache = "\n".join(lines)
        _kb_last_loaded = now
        return _kb_cache

    except socket.timeout:
        print(f"[Sheets] Bilgi Bankası oxuma timeout: API yavaş cavab verdi")
        return _kb_cache
    except Exception as e:
        print(f"[Sheets] Bilgi Bankası oxuma xətası: {e}")
        return _kb_cache


def add_knowledge_entry(sual: str, cavab: str, kateqoriya: str = "Ümumi") -> bool:
    """
    Bilgi Bankasına yeni sıra əlavə et.
    /kb komandası tərəfindən çağırılır.
    """
    global _kb_cache, _kb_last_loaded

    try:
        client = _get_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = _get_or_create_worksheet(sheet, KNOWLEDGE_SHEET_NAME, KNOWLEDGE_HEADERS)

        ws.append_row([
            sual,
            cavab,
            kateqoriya,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ])

        _kb_cache = ""
        _kb_last_loaded = None

        print(f"[Sheets] Bilgi Bankasına əlavə edildi: {sual[:50]}")
        return True

    except socket.timeout:
        print(f"[Sheets] Bilgi əlavə timeout: API yavaş cavab verdi")
        return False
    except Exception as e:
        print(f"[Sheets] Bilgi əlavə xətası: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# LEAD YAZMA
# ─────────────────────────────────────────────────────────────

LEADS_HEADERS = [
    "AD", "Soyad", "Telefon", "Email", "Budce",
    "Maraq Yerleri", "Lead Skoru", "Proyekt",
    "Zeng Vaxti", "Durum", "Yatirim Zamani",
    "Son Mesaj", "Source", "Tarix/Saat", "Telegram ID"
]


def _lead_to_row(lead: dict) -> list:
    return [
        lead.get("ad", ""),
        lead.get("soyad", ""),
        lead.get("telefon", ""),
        lead.get("email", ""),
        lead.get("budce", ""),
        lead.get("maraq_yerleri", ""),
        lead.get("lead_skoru", ""),
        lead.get("proyekt", ""),
        lead.get("zeng_vaxti", ""),
        lead.get("durum", "Yeni"),
        lead.get("yatirim_zamani", ""),
        lead.get("son_mesaj", ""),
        lead.get("source", "Telegram"),
        lead.get("tarix", datetime.now().strftime("%Y-%m-%d %H:%M")),
        lead.get("user_id", ""),
    ]


def append_lead_to_sheet(lead: dict) -> bool:
    """Lead məlumatlarını Google Sheets-ə əlavə et (timeout qorunmuş)."""
    try:
        client = _get_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = _get_or_create_worksheet(sheet, LEADS_SHEET_NAME, LEADS_HEADERS)
        ws.append_row(_lead_to_row(lead))
        return True
    except socket.timeout:
        print(f"[Sheets] Lead yazma timeout: Google API yavaş cavab verdi. Lead #{lead.get('id')} kənarlaşdırıldı.")
        return False
    except Exception as e:
        print(f"[Sheets] Lead yazma xətası: {e}")
        return False


def update_lead_in_sheet(lead: dict) -> bool:
    """Mövcud lead-i Sheets-də tap və yenilə (telefon nömrəsi əsasında)."""
    try:
        client = _get_client()
        sheet = client.open_by_key(GOOGLE_SHEET_ID)
        ws = _get_or_create_worksheet(sheet, LEADS_SHEET_NAME, LEADS_HEADERS)

        telefon = lead.get("telefon", "")
        if not telefon:
            return append_lead_to_sheet(lead)

        cell = ws.find(telefon)
        if cell:
            row_num = cell.row
            ws.update(f"A{row_num}:O{row_num}", [_lead_to_row(lead)])
            return True
        else:
            return append_lead_to_sheet(lead)

    except socket.timeout:
        print(f"[Sheets] Lead yeniləmə timeout: Google API cavab vermədi. Lead #{lead.get('id')} saklanıldı.")
        return False
    except Exception as e:
        print(f"[Sheets] Lead yeniləmə xətası: {e}")
        return False
