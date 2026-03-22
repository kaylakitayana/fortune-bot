import io
import json
import uuid
import re

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

app = FastAPI()

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
            "message": "Limit reached",
            "session_id": session_id,
            "remaining": 0
        })

    lots = data["divination_lots"]

    lot_number = extract_lot_number(body.question)
    lot = find_lot(lot_number, lots)

    if not lot:
        return {
            "ok": True,
            "answer": "Include a lot number (1–100)",
            "session_id": session_id,
            "remaining": total_allowed - used
        }

    answer = lot["interpretation_en"]

    session["used"] += 1

    return {
        "ok": True,
        "answer": answer,
        "session_id": session_id,
        "remaining": total_allowed - session["used"]
    }