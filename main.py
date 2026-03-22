import json
import uuid
import re

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


session_store = {}


class AskBody(BaseModel):
    question: str
    session_id: str | None = None


class UnlockBody(BaseModel):
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


def find_lot(lot_number, lots):
    for lot in lots:
        if str(lot.get("lot_number")) == str(lot_number):
            return lot
    return None


def generate_fortune_response(lot, question, history):
    grade = lot.get("grade", "")
    zh_text = lot.get("interpretation_zh", "")
    en_text = lot.get("interpretation_en", "")

    is_chinese = bool(re.search(r"[\u4e00-\u9fff]", question))
    is_follow_up = len(history) > 0

    q = question.lower()

    if grade == "上":
        opening_en = "This is a favorable sign."
        opening_zh = "此签属吉兆。"
    elif grade == "中":
        opening_en = "This is a steady sign."
        opening_zh = "此签属中平之象。"
    else:
        opening_en = "This sign calls for caution."
        opening_zh = "此签提醒你凡事宜谨慎。"

    if "work" in q or "career" in q or "job" in q:
        focus_en = "In work matters, move steadily, avoid conflict, and let timing work in your favor."
        focus_zh = "在工作方面，宜稳中求进，避免冲突，顺时而行。"
    elif "love" in q or "relationship" in q:
        focus_en = "In matters of the heart, patience and honest communication will help more than force."
        focus_zh = "在感情方面，耐心与坦诚沟通，比急于推进更有帮助。"
    elif "money" in q or "wealth" in q or "finance" in q:
        focus_en = "For financial matters, act prudently, avoid haste, and choose clear opportunities over risky ones."
        focus_zh = "在财运方面，宜谨慎行事，不可急进，宁取稳健之机。"
    else:
        focus_en = "For this matter, balance effort with patience and do not rush what has not yet ripened."
        focus_zh = "就此事而言，宜在努力中保持耐心，不可操之过急。"

    follow_en = "This follows naturally from your earlier reading." if is_follow_up else "This is your first reading for this matter."
    follow_zh = "这是延续你前面的签意。" if is_follow_up else "这是你此事的初次解读。"

    blessing_en = "Trust the timing of events."
    blessing_zh = "顺势而行，自有转机。"

    if is_chinese:
        source_line = zh_text.split("\n")[0] if zh_text else ""
        return f"{opening_zh}{follow_zh}{focus_zh} 签意提示：{source_line}。{blessing_zh}"

    source_line = en_text.split("\n")[0] if en_text else ""
    return f"{opening_en} {follow_en} {focus_en} The lot points to this image: {source_line}. {blessing_en}"


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
def unlock(body: UnlockBody):
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

    lot = None

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