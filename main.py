import json
import uuid
import re

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

app = FastAPI()

# Render health check
@app.get("/health")
def health():
    return {"status": "ok"}


session_store = {}

class AskBody(BaseModel):
    question: str
    session_id: str | None = None


def load_knowledge():
    with open("knowledge.json", "r", encoding="utf-8") as f:
        return json.load(f)


def get_session(session_id):
    if session_id not in session_store:
        session_store[session_id] = {
            "used": 0,
            "paid": 0,
            "history": [],
            "current_lot": None
        }
    return session_store[session_id]


def extract_lot_number(q):
    m = re.search(r"(\d{1,3})", q)
    return m.group(1) if m else None


def find_lot(lot_number, lots):
    for lot in lots:
        if str(lot["lot_number"]) == lot_number:
            return lot
    return None


def generate_fortune_response(lot, question, history):

    grade = lot.get("grade", "")

    # Tone logic (concise)
    if grade == "上":
        tone = "A favorable sign appears."
        advice = "Move forward with confidence."
    elif grade == "中":
        tone = "The situation is steady."
        advice = "Stay patient and consistent."
    else:
        tone = "Caution is advised."
        advice = "Avoid rushing decisions."

    # Follow-up awareness
    follow = "The situation is still unfolding." if history else "This is your initial insight."

    # Context awareness
    q = question.lower()
    if "work" in q:
        focus = "In work matters, stay steady and avoid conflict."
    elif "love" in q or "relationship" in q:
        focus = "In relationships, be patient and communicate clearly."
    else:
        focus = "Balance your actions with careful thinking."

    return f"{tone} {follow} {focus} {advice} Trust the timing of events."


@app.get("/", response_class=HTMLResponse)
def home():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/paynow-qr")
def paynow():
    return FileResponse("PayNow.jpeg")


@app.get("/paylah-qr")
def paylah():
    return FileResponse("PayLah.jpeg")


@app.post("/unlock")
def unlock(body: dict):
    session = get_session(body["session_id"])
    session["paid"] += 10
    return {"ok": True}


@app.post("/ask")
def ask(body: AskBody):

    data = load_knowledge()
    free_limit = data["free_limit"]

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

    lots = data["divination_lots"]

    lot_number = extract_lot_number(body.question)

    if lot_number:
        lot = find_lot(lot_number, lots)
        if lot:
            session["current_lot"] = lot
    else:
        lot = session.get("current_lot")

    if not lot:
        return {
            "ok": True,
            "answer": "Ask your question below. Please include the lot number (choose between 1-100), for example: How is my work fortune for this week? Lot 12 or 我这周的运势如何？ 第12签。",
            "session_id": session_id,
            "remaining": total_allowed - used
        }

    answer = generate_fortune_response(lot, body.question, session["history"])

    session["history"].append({
        "q": body.question,
        "a": answer
    })

    session["history"] = session["history"][-10:]

    session["used"] += 1

    return {
        "ok": True,
        "answer": answer,
        "session_id": session_id,
        "remaining": total_allowed - session["used"]
    }