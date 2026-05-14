"""
agent.py — AI Agent məntiqi.

1. Language Detector  → istifadəçinin dilini müəyyən edir
2. Intent Classifier  → istifadəçinin niyyətini müəyyən edir
3. Q&A Agent          → Bilgi Bankasından istifadə edərək cavab verir
4. Lead Extractor     → söhbətdən lead məlumatlarını çıxarır
"""
import json
import re
from datetime import datetime, timedelta
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL, dubai_now
from prompts import SYSTEM_PROMPT
from memory import get_history, add_message, upsert_lead, get_lead
from sheets import get_knowledge_base
from calendar_service import create_meeting_event

client = Groq(api_key=GROQ_API_KEY)


# ─────────────────────────────────────────────────────────────
# DATE HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────

def _day_of_week_name(date_obj: datetime) -> str:
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return days[date_obj.weekday()]

def _next_weekday(from_date: datetime, target_day: int) -> datetime:
    current_day = from_date.weekday()
    current_day_ours = (current_day + 1) % 7
    days_ahead = target_day - current_day_ours
    if days_ahead <= 0:
        days_ahead += 7
    return from_date + timedelta(days=days_ahead)

def _parse_meeting_date(raw_date_str: str, from_date: datetime) -> str | None:
    if not raw_date_str:
        return None
    try:
        parts = raw_date_str.strip().split()
        if len(parts) < 2:
            return None
        date_part, time_part = parts[0], parts[1]
        date_obj = datetime.strptime(date_part, "%d.%m.%Y")
        time_match = re.match(r'^(\d{1,2}):(\d{2})$', time_part)
        if not time_match:
            return None
        today = from_date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_only = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        if date_only < today:
            return raw_date_str
        return raw_date_str
    except Exception as e:
        print(f"[Agent] Date parse error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# 1. LANGUAGE DETECTOR
# ─────────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    simple_greeting = text.lower().strip()
    if simple_greeting in ["salam", "saqol", "sagol", "necesen", "nəcəsən"]:
        return "az"
    if simple_greeting in ["merhaba", "selam", "nasılsın", "teşekkürler"]:
        return "tr"

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
                        "No other text, just the code.\n\n"
                        "IMPORTANT DISTINCTIONS:\n"
                        "- Azerbaijani (az) vs Turkish (tr): "
                        "Azerbaijani uses: nə, ən, mən, sən, nədir, edə, bilərəm, necə, üçün, xahiş, salam, necəsən, sağ ol, bəli, yaxşı, qəşəng. "
                        "Turkish uses: mı, mü, ne, ben, sen, nedir, eder, bilirim, nasıl, için, merhaba, nasılsın, teşekkür. "
                        "If the text contains ə (schwa) character, it is AZERBAIJANI (az), NOT Turkish.\n"
                        "- If the user says 'Salam', it's almost always AZERBAIJANI (az) or Turkish (tr).\n"
                        "- If unsure between two similar languages, prefer: az over tr for Turkic with ə."
                    )
                },
                {"role": "user", "content": text}
            ],
            temperature=0,
            max_tokens=5,
        )
        lang = response.choices[0].message.content.strip().lower()[:2]
        return lang if lang.isalpha() else "en"
    except Exception:
        return "en"


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
- TOPLANTI    → Wants to schedule a meeting/appointment
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
        valid = {"SUAL","ALMAQ","SATMAQ","ICARE","INVESTISIYA","AGENT","QEYD","TOPLANTI","DIGER"}
        return intent if intent in valid else "DIGER"
    except Exception as e:
        print(f"[Agent] Intent xətası: {e}")
        return "SUAL"


# ─────────────────────────────────────────────────────────────
# 3. LEAD EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_PROMPT = """
Extract lead information from the conversation history below.
Only extract information that is EXPLICITLY stated by the USER (client). Use null for unknown fields.

Today's date and time (Dubai, UTC+4): {today}
Today is: {today_name}

Return ONLY valid JSON, nothing else:

{{
  "name": null,
  "surname": null,
  "telephone": null,
  "email": null,
  "budget": null,
  "place": null,
  "property_style": null,
  "meeting_time": null
}}

CRITICAL RULES:
- ONLY extract info from USER messages, NEVER from ASSISTANT messages!
- "İlkin", "Ilkin", "Mr. İlkin", "Chalabi" is the AGENT/OWNER name, NOT the client!
  NEVER extract these as the client's name or surname!
- "name": Client's first name ONLY
- "surname": Client's last name / family name ONLY
  If user writes full name like "Muhammad Rasul", split: name="Muhammad", surname="Rasul"
- "telephone": Write EXACTLY as the user typed it. Do NOT change digits!
- "email": Extract EXACTLY AS THE USER TYPED IT!
- "budget": Budget amount (e.g. "$500,000", "$1.5 million")
- "place": Area/location of interest
- "property_style": Type of property
- "meeting_time": MUST be in DD.MM.YYYY HH:MM format using today's date as reference.
"""

VALID_PROPERTY_TYPES = {
    "villa", "apartment", "studio", "penthouse", "townhouse", "duplex",
    "flat", "condo", "mansion", "loft", "bungalow", "house",
    "1-bedroom", "2-bedroom", "3-bedroom", "4-bedroom", "5-bedroom",
    "1 bedroom", "2 bedroom", "3 bedroom", "4 bedroom", "5 bedroom",
    "1-bed", "2-bed", "3-bed", "4-bed", "5-bed",
}


def _clean_extracted_data(data: dict, today_dt: datetime = None) -> dict:
    if today_dt is None:
        today_dt = dubai_now()

    AGENT_NAMES = {"ilkin", "chalabi", "mr. ilkin", "mr. İlkin"}
    name = data.get("name", "")
    surname = data.get("surname", "")
    if name and name.lower().strip() in {n.lower() for n in AGENT_NAMES}:
        data.pop("name", None)
        name = ""
    if surname and surname.lower().strip() in {n.lower() for n in AGENT_NAMES}:
        data.pop("surname", None)
        surname = ""

    name = data.get("name", "")
    surname = data.get("surname", "")
    if name and not surname:
        parts = name.strip().split()
        if len(parts) >= 2:
            data["name"] = parts[0]
            data["surname"] = " ".join(parts[1:])

    property_style = data.get("property_style", "")
    if property_style:
        prop_lower = property_style.lower().strip()
        is_valid = any(pt in prop_lower for pt in VALID_PROPERTY_TYPES)
        if not is_valid:
            data.pop("property_style", None)

    meeting_time = data.get("meeting_time", "")
    if meeting_time:
        mt_match = re.match(r'^\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}$', meeting_time.strip())
        if not mt_match:
            data.pop("meeting_time", None)
        else:
            parsed = _parse_meeting_date(meeting_time, today_dt)
            if parsed:
                data["meeting_time"] = parsed
            else:
                data.pop("meeting_time", None)

    telephone = data.get("telephone", "")
    if telephone:
        digits = re.sub(r'[^0-9]', '', telephone)
        if len(digits) < 7:
            data.pop("telephone", None)
        else:
            clean = telephone.strip()
            if clean.startswith("+"):
                data["telephone"] = clean
            elif clean.startswith("00"):
                data["telephone"] = "+" + clean[2:]
            elif clean.startswith("0"):
                data["telephone"] = "+971" + clean[1:]
            else:
                data["telephone"] = "+971" + clean

    email = data.get("email", "")
    if email and "@" not in email:
        data.pop("email", None)

    return data


def extract_lead_data(user_id: str, last_message: str) -> dict:
    try:
        history = get_history(user_id)
        history_text = "\n".join(
            [f"{m['role'].upper()}: {m['content']}" for m in history[-10:]]
        )
        today_dt = dubai_now()
        today_str = today_dt.strftime("%d.%m.%Y %H:%M (%A)")
        today_name = _day_of_week_name(today_dt)

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": EXTRACT_PROMPT.format(today=today_str, today_name=today_name)},
                {"role": "user", "content": f"Conversation:\n{history_text}\n\nLatest message: {last_message}"}
            ],
            temperature=0,
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            data = {k: v for k, v in data.items() if v and v != "null"}
            data = _clean_extracted_data(data, today_dt)
            return data
        return {}
    except Exception as e:
        print(f"[Agent] Lead extract xətası: {e}")
        return {}


# ─────────────────────────────────────────────────────────────
# 4. LEAD SKORU
# ─────────────────────────────────────────────────────────────

def calculate_lead_score(lead: dict) -> str:
    score = 0
    if lead.get("telephone"):      score += 30
    if lead.get("name"):           score += 10
    if lead.get("surname"):        score += 5
    if lead.get("email"):          score += 10
    if lead.get("budget"):         score += 15
    if lead.get("place"):          score += 10
    if lead.get("property_style"): score += 10
    if lead.get("meeting_time"):   score += 10

    if score >= 70:   return "🔥 Hot"
    elif score >= 40: return "🟡 Warm"
    else:             return "❄️ Cold"


# ─────────────────────────────────────────────────────────────
# 5. MEETING EXTRACTOR
# ─────────────────────────────────────────────────────────────

MEETING_EXTRACT_PROMPT = """
Analyze the conversation and determine if a meeting/appointment is being scheduled.

Today's date is: {today}

If a meeting IS being scheduled, extract the details and return JSON:
{{
  "has_meeting": true,
  "client_name": "name or null",
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "duration_minutes": 60,
  "budget": "budget or null",
  "area_of_interest": "area or null",
  "notes": "any additional details"
}}

If NO meeting is being scheduled, return:
{{
  "has_meeting": false
}}

Return ONLY valid JSON, nothing else.
"""


def extract_meeting_data(user_id: str, last_message: str) -> dict | None:
    try:
        history = get_history(user_id)
        history_text = "\n".join(
            [f"{m['role'].upper()}: {m['content']}" for m in history[-10:]]
        )
        today = dubai_now().strftime("%Y-%m-%d (%A)")
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": MEETING_EXTRACT_PROMPT.format(today=today)},
                {"role": "user", "content": f"Conversation:\n{history_text}\n\nLatest message: {last_message}"}
            ],
            temperature=0,
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if data.get("has_meeting"):
                return data
        return None
    except Exception as e:
        print(f"[Agent] Meeting extract xətası: {e}")
        return None


def _validate_and_fix_date(date_str: str, time_str: str) -> datetime | None:
    import calendar as cal
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            parts = date_str.split("-")
            if len(parts) == 3:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                max_day = cal.monthrange(year, month)[1]
                if day > max_day:
                    day = max_day
                return datetime(year, month, day,
                              int(time_str.split(":")[0]),
                              int(time_str.split(":")[1]))
        except Exception as e:
            print(f"[Agent] Could not fix date {date_str}: {e}")
    return None


def schedule_meeting(meeting_data: dict, lead_data: dict) -> str | None:
    try:
        date_str = meeting_data.get("date", "")
        time_str = meeting_data.get("time", "12:00")
        if not date_str:
            return None
        start_dt = _validate_and_fix_date(date_str, time_str)
        if not start_dt:
            return None
        duration = meeting_data.get("duration_minutes", 60)
        client_name = meeting_data.get("client_name") or lead_data.get("name", "Client")
        budget = meeting_data.get("budget") or lead_data.get("budget", "")
        area = meeting_data.get("area_of_interest") or lead_data.get("place", "")
        summary = f"🏠 Meeting with {client_name} - Property Consultation"
        desc_lines = [
            f"Client: {client_name}",
            f"Budget: {budget}" if budget else "",
            f"Area of Interest: {area}" if area else "",
            f"Phone: {lead_data.get('telephone', 'N/A')}",
            f"Email: {lead_data.get('email', 'N/A')}",
            f"Notes: {meeting_data.get('notes', '')}",
            "",
            "--- Auto-created by Real Estate AI Bot ---",
        ]
        description = "\n".join(line for line in desc_lines if line or line == "")
        result = create_meeting_event(
            summary=summary,
            description=description,
            start_datetime=start_dt,
            duration_minutes=duration,
            attendee_email=lead_data.get("email"),
        )
        if result:
            return result.get("htmlLink", "")
        return None
    except Exception as e:
        print(f"[Agent] Schedule meeting error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# 6. ANA CAVAB FUNKSİYASI
# ─────────────────────────────────────────────────────────────

def get_ai_response(user_id: str, user_name: str, user_message: str, media_context: str = None) -> tuple[str, str, str | None]:
    """
    İstifadəçinin mesajına AI cavabı qaytar.
    Returns: (cavab_mətni, intent, meeting_link_or_None)
    """
    lang = detect_language(user_message)
    intent = classify_intent(user_message)
    knowledge = get_knowledge_base()

    lang_names = {
        "en": "English", "az": "Azerbaijani", "tr": "Turkish",
        "ru": "Russian", "ar": "Arabic", "fr": "French",
        "de": "German", "es": "Spanish"
    }
    lang_name = lang_names.get(lang, "the same language as the user's message")
    lang_instruction = f"\n\n⚠️ CRITICAL: The user wrote in {lang_name}. You MUST reply in {lang_name}. Do NOT switch languages."

    system = SYSTEM_PROMPT + lang_instruction
    if knowledge:
        system += f"\n\n--- KNOWLEDGE BASE ---\n{knowledge}\n--- END ---\n"

    real_estate_intent_keywords = [
        "satmaq", "almaq", "icarə", "kirayə", "investisiya", "rent", "buy", "sell", "investment"
    ]
    real_estate_intents = {"ALMAQ", "SATMAQ", "ICARE", "INVESTISIYA"}
    allow_lead = (
        intent in real_estate_intents or
        (media_context and any(word in media_context.lower() for word in real_estate_intent_keywords))
    )
    if not allow_lead:
        system += "\n\n⚠️ CRITICAL INSTRUCTION: Do NOT ask the user for their contact details, name, phone number, email, or any lead generation form fields. Simply answer their question naturally."

    history = get_history(user_id)
    messages = [{"role": "system", "content": system}]
    messages.extend(history)

    ai_user_message = user_message
    if media_context:
        ai_user_message = f"{user_message}\n\n--- MEDIA CONTEXT ---\n{media_context}\n--- END MEDIA ---"
    messages.append({"role": "user", "content": ai_user_message})

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=400,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Agent] Groq xətası: {e}")
        error_msgs = {
            "en": "Sorry, I'm having a technical issue. Please try again in a moment. 🙏",
            "az": "Bağışlayın, texniki problem yaşayıram. Bir az sonra yenidən cəhd edin. 🙏",
            "tr": "Özür dilerim, teknik sorun yaşıyorum. Lütfen biraz sonra tekrar deneyin. 🙏",
            "ru": "Извините, у меня технические проблемы. Пожалуйста, попробуйте позже. 🙏",
        }
        answer = error_msgs.get(lang, error_msgs["en"])

    add_message(user_id, "user", user_message)
    add_message(user_id, "assistant", answer)

    lead_form_already_sent = any("📝 Name & Surname:" in m["content"] for m in history[-5:])
    lead_data = None
    real_estate_intents_full = {"ALMAQ", "SATMAQ", "ICARE", "INVESTISIYA", "TOPLANTI"}
    should_extract_lead = (intent in real_estate_intents_full) or (not lead_form_already_sent and any(word in user_message.lower() for word in real_estate_intent_keywords))

    if should_extract_lead:
        lead_data = extract_lead_data(user_id, user_message)

    skip_lead = not should_extract_lead and intent not in real_estate_intents_full
    if user_message.lower().strip() in ["salam", "hello", "hi", "merhaba", "selam"]:
        skip_lead = True

    if lead_data and not skip_lead:
        has_client_identity = lead_data.get("name") or lead_data.get("telephone")
        existing_lead = get_lead(user_id)
        if has_client_identity or existing_lead:
            lead_data["last_contact"] = dubai_now().strftime("%d.%m.%Y %H:%M")
            if existing_lead:
                merged = {k: v for k, v in existing_lead.items() if v}
                merged.update({k: v for k, v in lead_data.items() if v})
                lead_data = merged
            lead_data["lead_score"] = calculate_lead_score(lead_data)
            lead_data["agent"] = "Mr. İlkin"
            upsert_lead(user_id, user_name, lead_data)

    _meeting_keywords = {"meeting", "toplanti", "toplantı", "gorusme", "görüşmə",
                         "randevu", "appointment", "schedule", "meet", "görüş",
                         "tomorrow", "sabah", "yarın", "yarin", "bugün", "bugun", "today"}
    _has_meeting_hint = (
        intent == "TOPLANTI"
        or any(kw in user_message.lower() for kw in _meeting_keywords)
        or (lead_data and lead_data.get("meeting_time"))
    )

    meeting_link = None
    if _has_meeting_hint:
        meeting_data = extract_meeting_data(user_id, user_message)
        if meeting_data:
            current_lead = get_lead(user_id) or lead_data or {}
            meeting_link = schedule_meeting(meeting_data, current_lead)
            if meeting_link:
                try:
                    m_date = meeting_data.get("date", "")
                    m_time = meeting_data.get("time", "12:00")
                    if m_date:
                        m_dt = _validate_and_fix_date(m_date, m_time)
                        if m_dt:
                            meeting_time_formatted = m_dt.strftime("%d.%m.%Y %H:%M")
                            upsert_lead(user_id, user_name, {"meeting_time": meeting_time_formatted})
                except Exception as e:
                    print(f"[Agent] Meeting time save error: {e}")

    return answer, intent, meeting_link
