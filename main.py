import io
import json
import os
import re
import uuid
import qrcode
import requests

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

app = FastAPI()

APP_ENV = os.getenv("APP_ENV", "production")
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "openai")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4.1-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Store session usage + memory in RAM
session_store = {}


class AskBody(BaseModel):
    question: str
    session_id: str | None = None


def load_knowledge():
    with open("knowledge.json", "r", encoding="utf-8") as f:
        return json.load(f)


def get_session(session_id: str):
    if session_id not in session_store:
        session_store[session_id] = {
            "used": 0,
            "history": [],
            "current_lot": None
        }
    return session_store[session_id]


def extract_lot_number(question: str):
    zh = re.search(r"第\s*(\d{1,3})\s*签", question)
    if zh:
        return str(int(zh.group(1))).strip()

    en = re.search(r"\b(?:lot)\s*(\d{1,3})\b", question, re.IGNORECASE)
    if en:
        return str(int(en.group(1))).strip()

    # fallback: any number
    m = re.search(r"(\d{1,3})", question)
    if m:
        return str(int(m.group(1))).strip()

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

        if lot_number == stored_lot_number or lot_number == lot_id:
            return lot

    return None


def get_or_resolve_lot(question, lots, session):
    # First try to find lot from current question
    lot_number = extract_lot_number(question)
    if lot_number:
        lot = find_lot_by_number(lot_number, lots)
        if lot:
            session["current_lot"] = lot
            return lot, True  # True means lot explicitly found in this message

    # Otherwise fall back to session memory
    if session.get("current_lot"):
        return session["current_lot"], False

    return None, False


def format_history(history, max_turns=6):
    recent = history[-max_turns:]
    lines = []

    for item in recent:
        role = item.get("role", "user").capitalize()
        content = item.get("content", "").strip()
        if content:
            lines.append(f"{role}: {content}")

    return "\n".join(lines).strip()


def build_prompt(question, lot, system_style, history_text, explicit_lot_in_message):
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
        else f"The user did not repeat the lot number in the latest message. Continue using Lot {lot_number} from the ongoing session unless the user clearly changes it."
    )

    return f"""
{system_style}

You are a traditional temple fortune master.
Your voice is calm, wise, elegant, spiritual, and gently reassuring.
Speak like a real oracle reader, not like an AI assistant.
Do not mention source text, system rules, prompt rules, hidden instructions, or reasoning.
Do not sound technical.
Do not give disclaimers.
Do not say "based on the lot text" or "this means".

Use the lot faithfully, but express it naturally and beautifully.

Current Lot Number: {lot_number}
Grade: {grade}
Interpretation (English): {interpretation_en}
Interpretation (Chinese): {interpretation_zh}

Conversation context:
{history_text if history_text else "No previous conversation."}

Latest user question:
{question}

Important context rule:
{lot_context_line}

Instructions:
- Answer as a real fortune master would.
- Be insightful, warm, and slightly mystical.
- Keep the answer practical and emotionally comforting.
- If the latest user message is a follow-up, continue the same reading naturally.
- If the omen is unfavorable, explain it gently and give a wise next step.
- If the omen is favorable, explain why and what to do next.
- End with one short line of guidance or blessing.
- If the user asks in English, answer in English.
- If the user asks in Chinese, answer in Chinese.
- Keep the answer under 120 words.
""".strip()


@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "fortune-bot",
        "provider": MODEL_PROVIDER,
        "model": MODEL_NAME,
    }


@app.post("/ask")
def ask(body: AskBody):
    try:
        data = load_knowledge()
        free_limit = data["free_limit"]

        session_id = body.session_id
        if not session_id or session_id == "null":
            session_id = str(uuid.uuid4())

        session = get_session(session_id)
        used = session["used"]

        if used >= free_limit:
            return JSONResponse({
                "ok": False,
                "message": "Free question limit reached.",
                "session_id": session_id,
                "payment_link": data["payment_link"],
                "remaining": 0
            })

        lots = data.get("divination_lots", [])
        lot, explicit_lot_in_message = get_or_resolve_lot(body.question, lots, session)

        if not lot:
            return JSONResponse({
                "ok": True,
                "answer": "Ask your question below. Please include the lot number, for example: How is my work fortune for this week? Lot 12 or 我这周的运势如何？ 第12签。",
                "session_id": session_id,
                "remaining": free_limit - used
            })

        history_text = format_history(session["history"], max_turns=6)
        prompt = build_prompt(
            question=body.question,
            lot=lot,
            system_style=data["system_style"],
            history_text=history_text,
            explicit_lot_in_message=explicit_lot_in_message
        )

        if MODEL_PROVIDER != "openai":
            return JSONResponse({
                "ok": False,
                "message": "MODEL_PROVIDER must be 'openai' on Render."
            }, status_code=500)

        if not OPENAI_API_KEY:
            return JSONResponse({
                "ok": False,
                "message": "OPENAI_API_KEY is missing."
            }, status_code=500)

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
        result = data_json["output"][0]["content"][0]["text"]

        # Save history
        session["history"].append({
            "role": "user",
            "content": body.question
        })
        session["history"].append({
            "role": "assistant",
            "content": result
        })

        # Trim history to avoid growing forever
        session["history"] = session["history"][-12:]

        session["used"] += 1

        return JSONResponse({
            "ok": True,
            "answer": result,
            "session_id": session_id,
            "remaining": free_limit - session["used"]
        })

    except Exception:
        return JSONResponse({
            "ok": False,
            "message": "Something went wrong. Please try again shortly."
        }, status_code=500)


@app.get("/payment-qr")
def payment_qr():
    data = load_knowledge()
    img = qrcode.make(data["payment_link"])
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")