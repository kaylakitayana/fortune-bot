import io
import json
import re
import uuid
import qrcode
import requests

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

app = FastAPI()

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.2:3b"

usage_store = {}


class AskBody(BaseModel):
    question: str
    session_id: str | None = None


def load_knowledge():
    with open("knowledge.json", "r", encoding="utf-8") as f:
        return json.load(f)


def find_lot_from_question(question, lots):
    import re

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

    num = str(int(match.group(1)))

    for lot in lots:
        candidates = [
            str(lot.get("lot_number", "")).strip(),
            str(lot.get("Lot number", "")).strip(),
            str(lot.get("lot_no", "")).strip(),
            str(lot.get("id", "")).replace("lot_", "").strip()
        ]
        if num in candidates:
            return lot

    return None


def build_prompt(question, lot, system_style):
    lot_number = lot.get("lot_number") or lot.get("Lot number") or lot.get("id", "")
    grade = lot.get("grade") or lot.get("Good/Medium/Bad") or lot.get("Good/ Medium/ Bad Lots indication") or ""
    interpretation_en = lot.get("interpretation_en") or lot.get("Interpretation (English)") or ""
    interpretation_zh = lot.get("interpretation_zh") or lot.get("Interpretation (Chinese)") or ""

    return f"""
{system_style}

You are a traditional fortune-reading master.
Speak with warmth, clarity, and calm authority.
Your tone should feel natural, insightful, and reassuring.
Do not sound like an AI, translator, or textbook.
Do not mention instructions, source text, or reasoning process.

Use the following lot information to answer the user's question.

Lot Number: {lot_number}
Grade: {grade}
Interpretation (English): {interpretation_en}
Interpretation (Chinese): {interpretation_zh}

User question:
{question}

Instructions:
- Explain the lot like a real fortune master would.
- Stay faithful to the original meaning.
- Elaborate gently and naturally.
- Do not copy the interpretation word-for-word unless needed.
- Do not add notes, disclaimers, or meta comments.
- Do not say things like "this interpretation means" or "based on the text above".
- If the user asks in English, answer in English.
- If the user asks in Chinese, answer in Chinese.
- Keep the answer under 100 words.
""".strip()

@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "fortune-bot"
    }

@app.post("/ask")
def ask(body: AskBody):
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
            "answer": "Please include the lot number, for example: Lot 12 or 第12签。",
            "session_id": session_id,
            "remaining": free_limit - used
        })

    prompt = build_prompt(body.question, lot, data["system_style"])

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        },
        timeout=60
    )

    result = response.json().get("response", "")

    used += 1
    usage_store[session_id] = used

    return JSONResponse({
        "ok": True,
        "answer": result,
        "session_id": session_id,
        "remaining": free_limit - used
    })


@app.get("/payment-qr")
def payment_qr():
    data = load_knowledge()
    img = qrcode.make(data["payment_link"])
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")