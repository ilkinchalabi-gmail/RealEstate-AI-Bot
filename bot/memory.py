"""
memory.py — SQLite-based conversation memory.
Hər istifadəçi üçün son N mesaj saxlanılır (MEMORY_WINDOW).
"""

import sqlite3
import json
import os
from datetime import datetime
from config import MEMORY_WINDOW

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "memory.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   TEXT    NOT NULL,
            role      TEXT    NOT NULL,   -- 'user' | 'assistant'
            content   TEXT    NOT NULL,
            created_at TEXT   NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       TEXT,
            telegram_name TEXT,
            ad            TEXT,
            soyad         TEXT,
            telefon       TEXT,
            email         TEXT,
            budce         TEXT,
            maraq_yerleri TEXT,
            lead_skoru    TEXT,
            proyekt       TEXT,
            zeng_vaxti    TEXT,
            durum         TEXT  DEFAULT 'Yeni',
            yatirim_zamani TEXT,
            son_mesaj     TEXT,
            source        TEXT  DEFAULT 'Telegram',
            tarix         TEXT,
            sheets_synced INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


# ─────────────────────────────────────────────────────────────
# MESSAGE HISTORY
# ─────────────────────────────────────────────────────────────

def add_message(user_id: str, role: str, content: str):
    """Söhbəti DB-yə əlavə et və köhnə mesajları sil."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO messages (user_id, role, content, created_at) VALUES (?,?,?,?)",
        (str(user_id), role, content, datetime.now().isoformat())
    )
    conn.commit()

    # Yalnız son MEMORY_WINDOW mesajı saxla
    rows = conn.execute(
        "SELECT id FROM messages WHERE user_id=? ORDER BY id DESC",
        (str(user_id),)
    ).fetchall()
    if len(rows) > MEMORY_WINDOW:
        old_ids = [r[0] for r in rows[MEMORY_WINDOW:]]
        conn.execute(f"DELETE FROM messages WHERE id IN ({','.join('?' * len(old_ids))})", old_ids)
        conn.commit()
    conn.close()


def get_history(user_id: str) -> list[dict]:
    """Söhbət tarixçəsini OpenAI format-da qaytar."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE user_id=? ORDER BY id ASC",
        (str(user_id),)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in rows]


def clear_history(user_id: str):
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE user_id=?", (str(user_id),))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# LEAD MANAGEMENT
# ─────────────────────────────────────────────────────────────

def upsert_lead(user_id: str, telegram_name: str, data: dict):
    """Lead məlumatlarını yarat və ya yenilə."""
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM leads WHERE user_id=?", (str(user_id),)
    ).fetchone()

    data["tarix"] = data.get("tarix", datetime.now().isoformat())

    if existing:
        fields = ", ".join([f"{k}=?" for k in data.keys()])
        values = list(data.values()) + [str(user_id)]
        conn.execute(f"UPDATE leads SET {fields}, sheets_synced=0 WHERE user_id=?", values)
    else:
        data["user_id"] = str(user_id)
        data["telegram_name"] = telegram_name
        data["source"] = "Telegram"
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        conn.execute(f"INSERT INTO leads ({cols}) VALUES ({placeholders})", list(data.values()))

    conn.commit()
    conn.close()


def get_lead(user_id: str) -> dict | None:
    """İstifadəçinin lead məlumatlarını qaytar."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM leads WHERE user_id=?", (str(user_id),)
    ).fetchone()
    conn.close()
    if not row:
        return None
    cols = [c[0] for c in conn.execute("PRAGMA table_info(leads)").description] if False else [
        "id","user_id","telegram_name","ad","soyad","telefon","email","budce",
        "maraq_yerleri","lead_skoru","proyekt","zeng_vaxti","durum","yatirim_zamani",
        "son_mesaj","source","tarix","sheets_synced"
    ]
    # Re-open for column names
    conn2 = _get_conn()
    row2 = conn2.execute("SELECT * FROM leads WHERE user_id=?", (str(user_id),)).fetchone()
    cursor = conn2.execute("SELECT * FROM leads WHERE user_id=?", (str(user_id),))
    col_names = [description[0] for description in cursor.description]
    conn2.close()
    return dict(zip(col_names, row2)) if row2 else None


def get_unsynced_leads() -> list[dict]:
    """Google Sheets-ə yazılmamış lead-ləri qaytar."""
    conn = _get_conn()
    cursor = conn.execute("SELECT * FROM leads WHERE sheets_synced=0")
    col_names = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(col_names, r)) for r in rows]


def mark_lead_synced(lead_id: int):
    conn = _get_conn()
    conn.execute("UPDATE leads SET sheets_synced=1 WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
