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

usage_store = {}


class AskBody(BaseModel):
    question: str
    session_id: str | None = None


def load_knowledge():
    with open("knowledge.json", "r", encoding="utf-8") as f:
        return json.load(f)


def find_lot_from_question(question, lots):
    print("QUESTION RECEIVED:", repr(question))

    m = re.search(r"(\d{1,3})", question)
    if not m:
        zh = re.search(r"第\s*(\d{1,3})\s*签", question)
        if zh:
            m = zh

    if not m:
        print("NO NUMBER FOUND")
        return None

    num = str(int(m.group(1))).strip()
    print("NUMBER FOUND:", num)

    for lot in lots:
        lot_number = str(
            lot.get("lot_number")
            or lot.get("Lot number")
            or lot.get("lot no")
            or lot.get("lot_no")
            or ""
        ).strip()

        lot_id = str(lot.get("id", "")).replace("lot_", "").strip()

        if num == lot_number or num == lot_id:
            print("MATCHED LOT:", lot)
            return lot

    print("NO MATCHING LOT IN JSON")
    return None


def build_prompt(question, lot, system_style):
    lot_number = lot.get("lot_number") or lot.get("Lot number") or lot.get("id", "")
    grade = lot.get("grade") or lot.get("Good/Medium/Bad") or lot.get("Good/ Medium/ Bad Lots indication") or ""
    interpretation_en = lot.get("interpretation_en") or lot.get("Interpretation (English)") or ""
    interpretation_zh = lot.get("interpretation_zh") or lot.get("Interpretation (Chinese)") or ""

    return f"""
{system_style}

You are a traditional temple fortune master.
Your voice is calm, wise, elegant, spiritual, and gently reassuring.
Speak like a real oracle reader, not like an AI assistant.
Do not mention source text, system rules, or reasoning.
Do not sound technical.
Do not give disclaimers.
Do not say "based on the lot text" or "this means".

Use the lot faithfully, but express it naturally and beautifully.

Lot Number: {lot_number}
Grade: {grade}
Interpretation (English): {interpretation_en}
Interpretation (Chinese): {interpretation_zh}

User question:
{question}

Instructions:
- Answer as a real fortune master would.
- Be insightful, warm, and slightly mystical.
- Keep the answer practical and emotionally comforting.
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

        used = usage_store.get(session_id, 0)

        if used >= free_limit:
            return JSONResponse({
                "ok": False,
                "message": "Free question limit reached.",
                "session_id": session_id,
                "payment_link": data["payment_link"],
                "remaining": 0
            })

        lots = data.get("divination_lots", [])
        lot = find_lot_from_question(body.question, lots)

        if not lot:
            return JSONResponse({
                "ok": True,
                "answer": "Ask your question below. Please include the lot number, for example: How is my work fortune for this week? Lot 12 or 我这周的运势如何？ 第12签。",
                "session_id": session_id,
                "remaining": free_limit - used
            })

        prompt = build_prompt(body.question, lot, data["system_style"])

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

        used += 1
        usage_store[session_id] = used

        return JSONResponse({
            "ok": True,
            "answer": result,
            "session_id": session_id,
            "remaining": free_limit - used
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