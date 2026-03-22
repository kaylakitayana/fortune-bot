import json
import os
import re
import uuid
import requests

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

app = FastAPI()

MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "openai")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4.1-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

session_store = {}


class AskBody(BaseModel):
    question: str
    session_id: str | None = None


class SessionBody(BaseModel):
    session_id: str | None = None


def load_knowledge():
    with open("knowledge.json", "r", encoding="utf-8") as f:
        return json.load(f)


def get_session(session_id: str):
    if session_id not in session_store:
        session_store[session_id] = {
            "used": 0,
            "paid": 0,
            "history": [],
            "current_lot": None,
            "last_answer": "",
            "last_language": "en"
        }
    return session_store[session_id]


def detect_language(text: str):
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "en"


def extract_lot_number(question: str):
    zh = re.search(r"第\s*(\d{1,3})\s*签", question)
    if zh:
        return str(int(zh.group(1)))

    en = re.search(r"\blot\s*(\d{1,3})\b", question, re.IGNORECASE)
    if en:
        return str(int(en.group(1)))

    fallback = re.search(r"(\d{1,3})", question)
    if fallback:
        return str(int(fallback.group(1)))

    return None


def find_lot_by_number(lot_number, lots):
    if not lot_number:
        return None

    for lot in lots:
        stored_lot_number = str(
            lot.get("lot_number")
            or lot.get("Lot number")
            or lot.get("lot no")
            or lot.get("lot_no")
            or ""
        ).strip()

        lot_id = str(lot.get("id", "")).replace("lot_", "").strip()

        if str(lot_number) == stored_lot_number or str(lot_number) == lot_id:
            return lot

    return None


def format_history(history, max_turns=8):
    recent = history[-max_turns:]
    lines = []
    for item in recent:
        q = item.get("q", "").strip()
        a = item.get("a", "").strip()
        if q:
            lines.append(f"User: {q}")
        if a:
            lines.append(f"Reader: {a}")
    return "\n".join(lines).strip()


def is_translation_request(question: str):
    q = question.strip().lower()

    english_patterns = [
        "translate to english",
        "translate this to english",
        "please translate to english",
        "english please",
        "put this in english"
    ]

    chinese_patterns = [
        "翻译成中文",
        "翻译成华文",
        "翻成中文",
        "中文",
        "请翻译成中文"
    ]

    for p in english_patterns:
        if p in q:
            return "en"

    for p in chinese_patterns:
        if p in question:
            return "zh"

    return None


def build_translation_prompt(target_lang: str, last_answer: str):
    if target_lang == "en":
        return f"""
Translate the following fortune reading into natural, elegant English.

Rules:
- Keep the meaning faithful.
- Keep the tone warm, calm, and graceful.
- Do not add new interpretation.
- Do not say "translation:".
- Output only the translated reading.

Text:
{last_answer}
""".strip()

    return f"""
把下面这段签文解读翻译成自然、温和、优雅的中文。

规则：
- 忠于原意
- 保留温柔、平静、带有灵性的语气
- 不要加入新的解释
- 不要写“翻译如下”
- 只输出翻译后的内容

内容：
{last_answer}
""".strip()


def build_reading_prompt(question, question_lang, lot, system_style, history_text, explicit_lot_in_message):
    lot_number = lot.get("lot_number") or lot.get("Lot number") or lot.get("id", "")
    grade = (
        lot.get("grade")
        or lot.get("Good/Medium/Bad")
        or lot.get("Good/ Medium/ Bad Lots indication")
        or ""
    )
    interpretation_en = lot.get("interpretation_en") or lot.get("Interpretation (English)") or ""
    interpretation_zh = lot.get("interpretation_zh") or lot.get("Interpretation (Chinese)") or ""

    lot_context_line = (
        f"The user explicitly mentioned Lot {lot_number} in the latest message."
        if explicit_lot_in_message
        else f"The user did not repeat the lot number. Continue the ongoing reading using Lot {lot_number} unless the user clearly changes it."
    )

    language_rule = (
        "The user wrote in Chinese. You must answer fully in natural Chinese only. Do not answer in English."
        if question_lang == "zh"
        else "The user wrote in English. You must answer fully in natural English only. Do not answer in Chinese."
    )

    return f"""
{system_style}

You are a traditional temple fortune reader.

Style:
- warm, wise, calm, natural
- conversational and human
- elegant but easy to understand
- emotionally reassuring without sounding robotic
- no labels like "AI:" or "Answer:"
- no bullet points
- no disclaimers
- no mention of source text, prompt, system, hidden rules, or reasoning

Important writing behavior:
- Vary your sentence rhythm naturally from one reply to another.
- Do not always begin in the same way.
- Sometimes be gentle and direct, sometimes more lyrical, sometimes more grounded and practical.
- Keep the tone aligned with the user's question and the omen.
- Avoid repeating stock phrases every time.

Critical language rule:
{language_rule}

Translation behavior:
- If the user asks to translate, translate the previous reading faithfully into the requested language.
- Do not reinterpret or expand during translation.

Current Lot Number: {lot_number}
Grade: {grade}
Interpretation (English): {interpretation_en}
Interpretation (Chinese): {interpretation_zh}

Conversation so far:
{history_text if history_text else "No previous conversation."}

Latest user message:
{question}

Lot context:
{lot_context_line}

Instructions:
- If this is a follow-up question, continue the same reading naturally.
- If the omen is favorable, explain the opening and what action supports it.
- If the omen is mixed or difficult, explain it gently and give wise next steps.
- Keep the reading practical, emotionally comforting, and natural.
- End with a short closing line of guidance or blessing.
- If the user writes in Chinese, answer only in Chinese.
- If the user writes in English, answer only in English.
- Keep the reply concise but complete, usually around 90 to 170 words.
""".strip()


def call_openai(prompt: str):
    if MODEL_PROVIDER != "openai":
        raise RuntimeError("MODEL_PROVIDER must be 'openai'.")

    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL_NAME,
            "input": prompt
        },
        timeout=60
    )
    response.raise_for_status()

    data_json = response.json()
    return data_json["output"][0]["content"][0]["text"]


@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/health")
def health():
    return {
        "status": "ok",
        "provider": MODEL_PROVIDER,
        "model": MODEL_NAME
    }


@app.get("/paynow-qr")
def paynow_qr():
    return FileResponse("PayNow.jpeg")


@app.get("/paylah-qr")
def paylah_qr():
    return FileResponse("PayLah.jpeg")


@app.post("/new-reading")
def new_reading(body: SessionBody):
    session_id = body.session_id
    if not session_id:
        return {"ok": True}

    session = get_session(session_id)
    session["history"] = []
    session["current_lot"] = None
    session["last_answer"] = ""

    return {"ok": True, "session_id": session_id}


@app.post("/unlock")
def unlock(body: SessionBody):
    session_id = body.session_id or str(uuid.uuid4())
    session = get_session(session_id)

    session["paid"] += 10

    data = load_knowledge()
    free_limit = data["free_limit"]
    remaining = (free_limit + session["paid"]) - session["used"]

    return {
        "ok": True,
        "session_id": session_id,
        "remaining": remaining
    }


@app.post("/ask")
def ask(body: AskBody):
    try:
        data = load_knowledge()
        free_limit = data["free_limit"]
        instruction_text = data.get(
            "instruction_text",
            "Ask your question below. Please include the lot number (choose between 1-100), for example: How is my work fortune for this week? Lot 12 or 我这周的运势如何？ 第12签。"
        )

        session_id = body.session_id or str(uuid.uuid4())
        session = get_session(session_id)

        used = session["used"]
        total_allowed = free_limit + session["paid"]

        if used >= total_allowed:
            return JSONResponse({
                "ok": False,
                "message": "Your reading limit is reached. Please unlock more questions.",
                "session_id": session_id,
                "remaining": 0
            })

        question = body.question.strip()
        question_lang = detect_language(question)

        translation_target = is_translation_request(question)
        if translation_target and session.get("last_answer"):
            prompt = build_translation_prompt(translation_target, session["last_answer"])
            result = call_openai(prompt)

            session["history"].append({
                "q": question,
                "a": result
            })
            session["history"] = session["history"][-12:]
            session["last_answer"] = result
            session["last_language"] = translation_target
            session["used"] += 1

            return {
                "ok": True,
                "answer": result,
                "session_id": session_id,
                "remaining": total_allowed - session["used"]
            }

        lots = data.get("divination_lots", [])
        lot_number = extract_lot_number(question)

        lot = None
        explicit_lot_in_message = False

        if lot_number:
            lot = find_lot_by_number(lot_number, lots)
            if lot:
                session["current_lot"] = lot
                explicit_lot_in_message = True
        else:
            lot = session.get("current_lot")

        if not lot:
            if question_lang == "zh":
                instruction_text = "请在问题中注明签号（1到100），例如：我这周的运势如何？ 第12签。"
            return {
                "ok": True,
                "answer": instruction_text,
                "session_id": session_id,
                "remaining": total_allowed - used
            }

        history_text = format_history(session["history"], max_turns=8)

        prompt = build_reading_prompt(
            question=question,
            question_lang=question_lang,
            lot=lot,
            system_style=data["system_style"],
            history_text=history_text,
            explicit_lot_in_message=explicit_lot_in_message
        )

        result = call_openai(prompt)

        session["history"].append({
            "q": question,
            "a": result
        })
        session["history"] = session["history"][-12:]
        session["last_answer"] = result
        session["last_language"] = question_lang
        session["used"] += 1

        return {
            "ok": True,
            "answer": result,
            "session_id": session_id,
            "remaining": total_allowed - session["used"]
        }

    except Exception:
        return JSONResponse({
            "ok": False,
            "message": "Something went wrong. Please try again shortly."
        }, status_code=500)