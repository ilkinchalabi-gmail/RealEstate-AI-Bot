"""
agent.py — AI Agent məntiqi.

1. Language Detector  → istifadəçinin dilini müəyyən edir
2. Intent Classifier  → istifadəçinin niyyətini müəyyən edir
3. Q&A Agent          → Bilgi Bankasından istifadə edərək cavab verir
4. Lead Extractor     → söhbətdən lead məlumatlarını çıxarır
"""

import json
import re
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from prompts import SYSTEM_PROMPT
from memory import get_history, add_message, upsert_lead, get_lead
from sheets import get_knowledge_base

client = Groq(api_key=GROQ_API_KEY)


# ─────────────────────────────────────────────────────────────
# 1. LANGUAGE DETECTOR
# ─────────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """
    İstifadəçinin yazdığı dili müəyyən edir.
    Qaytarır: 'az', 'en', 'tr', 'ru', 'ar' və s.
    """
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Detect the language of the user's message. "
                        "Reply with ONLY the 2-letter ISO 639-1 language code. "
                        "Examples: en, az, tr, ru, ar, fr, de. "
                        "No other text, just the code."
                    )
                },
                {"role": "user", "content": text}
            ],
            temperature=0,
            max_tokens=5,
        )
        lang = response.choices[0].message.content.strip().lower()[:2]
        return lang if lang.isalpha() else "az"
    except Exception:
        return "az"


# ─────────────────────────────────────────────────────────────
# 2. INTENT CLASSIFIER
# ─────────────────────────────────────────────────────────────

INTENT_PROMPT = """
You are an intent classifier for a real estate company.
Read the user's message and choose ONE category:

- SUAL        → General question (price, location, project info)
- ALMAQ       → Wants to buy property
- SATMAQ      → Wants to sell property
- ICARE       → Wants to rent/lease
- INVESTISIYA → Investment interest
- AGENT       → Looking for a broker/agent
- QEYD        → Providing personal info (name, phone, budget, email)
- DIGER       → None of the above

Reply with ONLY one word (e.g.: ALMAQ). Nothing else.
"""


def classify_intent(user_message: str) -> str:
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": INTENT_PROMPT},
                {"role": "user", "content": user_message}
            ],
            temperature=0,
            max_tokens=10,
        )
        intent = response.choices[0].message.content.strip().upper()
        valid = {"SUAL","ALMAQ","SATMAQ","ICARE","INVESTISIYA","AGENT","QEYD","DIGER"}
        return intent if intent in valid else "DIGER"
    except Exception as e:
        print(f"[Agent] Intent xətası: {e}")
        return "SUAL"


# ─────────────────────────────────────────────────────────────
# 3. LEAD EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_PROMPT = """
Extract lead information from the conversation history below.
Only extract information that is EXPLICITLY stated. Use null for unknown fields.
Return ONLY valid JSON, nothing else:

{
  "ad": null,
  "soyad": null,
  "telefon": null,
  "email": null,
  "budce": null,
  "maraq_yerleri": null,
  "proyekt": null,
  "yatirim_zamani": null
}
"""


def extract_lead_data(user_id: str, last_message: str) -> dict:
    """Söhbət tarixçəsindən lead məlumatlarını çıxar."""
    try:
        history = get_history(user_id)
        history_text = "\n".join(
            [f"{m['role'].upper()}: {m['content']}" for m in history[-10:]]
        )

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": f"Conversation:\n{history_text}\n\nLatest message: {last_message}"}
            ],
            temperature=0,
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return {k: v for k, v in data.items() if v and v != "null"}
        return {}
    except Exception as e:
        print(f"[Agent] Lead extract xətası: {e}")
        return {}


# ─────────────────────────────────────────────────────────────
# 4. LEAD SKORU
# ─────────────────────────────────────────────────────────────

def calculate_lead_score(lead: dict) -> str:
    score = 0
    if lead.get("telefon"):       score += 40
    if lead.get("ad"):            score += 15
    if lead.get("soyad"):         score += 10
    if lead.get("email"):         score += 10
    if lead.get("budce"):         score += 15
    if lead.get("maraq_yerleri"): score += 10

    if score >= 80:   return "🔥 İsti"
    elif score >= 50: return "🟡 Orta"
    else:             return "❄️ Soyuq"


# ─────────────────────────────────────────────────────────────
# 5. ANA CAVAB FUNKSİYASI
# ─────────────────────────────────────────────────────────────

def get_ai_response(user_id: str, user_name: str, user_message: str) -> tuple[str, str]:
    """
    İstifadəçinin mesajına AI cavabı qaytar.
    Returns: (cavab_mətni, intent)
    """

    # 1. Dili müəyyən et
    lang = detect_language(user_message)
    print(f"[Agent] Dil: {lang} | User: {user_id}")

    # 2. Intent müəyyən et
    intent = classify_intent(user_message)
    print(f"[Agent] Intent: {intent}")

    # 3. Bilgi Bankasını yüklə
    knowledge = get_knowledge_base()

    # 4. Dil instruksiyonu əlavə et
    lang_names = {
        "en": "English", "az": "Azerbaijani", "tr": "Turkish",
        "ru": "Russian", "ar": "Arabic", "fr": "French",
        "de": "German", "es": "Spanish"
    }
    lang_name = lang_names.get(lang, "the same language as the user's message")
    lang_instruction = f"\n\n⚠️ CRITICAL: The user wrote in {lang_name}. You MUST reply in {lang_name}. Do NOT switch languages."

    # 5. Sistem promptunu hazırla
    system = SYSTEM_PROMPT + lang_instruction
    if knowledge:
        system += f"\n\n--- KNOWLEDGE BASE ---\n{knowledge}\n--- END ---"

    # 6. Söhbət tarixçəsini al
    history = get_history(user_id)
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    # 7. AI-dən cavab al
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=200,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Agent] Groq xətası: {e}")
        # Xəta mesajı da istifadəçinin dilindədir
        error_msgs = {
            "en": "Sorry, I'm having a technical issue. Please try again in a moment. 🙏",
            "az": "Bağışlayın, texniki problem yaşayıram. Bir az sonra yenidən cəhd edin. 🙏",
            "tr": "Özür dilerim, teknik sorun yaşıyorum. Lütfen biraz sonra tekrar deneyin. 🙏",
            "ru": "Извините, у меня технические проблемы. Пожалуйста, попробуйте позже. 🙏",
        }
        answer = error_msgs.get(lang, error_msgs["en"])

    # 8. Söhbəti yaddaşa yaz
    add_message(user_id, "user", user_message)
    add_message(user_id, "assistant", answer)

    # 9. Lead məlumatlarını çıxar və saxla
    lead_data = extract_lead_data(user_id, user_message)
    if lead_data:
        lead_data["son_mesaj"] = user_message
        existing_lead = get_lead(user_id)
        if existing_lead:
            merged = {k: v for k, v in existing_lead.items() if v}
            merged.update({k: v for k, v in lead_data.items() if v})
            lead_data = merged
        lead_data["lead_skoru"] = calculate_lead_score(lead_data)
        upsert_lead(user_id, user_name, lead_data)

    return answer, intent
