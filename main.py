import json
import uuid
import re

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

app = FastAPI()

# ✅ Render health check
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
    text = lot.get("interpretation_en", "")

    # Tone by grade
    if grade == "上":
        tone = "A very favorable sign reveals itself."
        advice = "This is a time to move forward with confidence. What you seek is aligning in your favor."
    elif grade == "中":
        tone = "The path ahead is steady, though it requires patience."
        advice = "Stay grounded. Progress will come gradually, and persistence will bring results."
    else:
        tone = "The signs suggest a need for caution."
        advice = "Do not rush. Take a step back and observe carefully before making decisions."

    # Context awareness (follow-up feeling)
    if len(history) > 0:
        follow = "From what has already been revealed, the situation is still unfolding."
    else:
        follow = "This is the initial insight into your situation."

    # Light personalization
    q = question.lower()
    if "work" in q:
        focus = "In your work matters, remain steady and avoid unnecessary conflict."
    elif "love" in q or "relationship" in q:
        focus = "In matters of the heart, patience and understanding will guide you best."
    else:
        focus = "In your current situation, balance action with careful thought."

    return f"""
{tone}

{follow}

{focus}

{advice}

Trust the timing of events. What is meant to unfold will reveal itself in due course.
""".strip()


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
            "message": "Your current reading has reached its limit. Please unlock more questions to continue.",
            "session_id": session_id,
            "remaining": 0
        })

    lots = data["divination_lots"]

    lot_number = extract_lot_number(body.question)

    # ✅ If user provides new lot → update
    if lot_number:
        lot = find_lot(lot_number, lots)
        if lot:
            session["current_lot"] = lot
    else:
        lot = session.get("current_lot")

    # ❗ Force lot if none exists at all
    if not lot:
        return {
            "ok": True,
            "answer": "Please include your lot number (1–100) so the reading can be interpreted.",
            "session_id": session_id,
            "remaining": total_allowed - used
        }

    # 🔮 Generate response with memory
    answer = generate_fortune_response(
        lot,
        body.question,
        session["history"]
    )

    # Save history
    session["history"].append({
        "q": body.question,
        "a": answer
    })

    # keep last 10 messages
    session["history"] = session["history"][-10:]

    session["used"] += 1

    return {
        "ok": True,
        "answer": answer,
        "session_id": session_id,
        "remaining": total_allowed - session["used"]
    }