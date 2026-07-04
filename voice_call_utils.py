"""Voice call history for the voicebot dashboard."""

from __future__ import annotations

from datetime import datetime

from database import SessionLocal
from models import VoiceCallLog


def serialize_voice_call(log: VoiceCallLog) -> dict:
    return {
        "id": log.id,
        "call_sid": log.call_sid,
        "caller_number": log.caller_number or "",
        "transcript": log.transcript or "",
        "started_at": log.started_at.isoformat() if log.started_at else None,
        "ended_at": log.ended_at.isoformat() if log.ended_at else None,
    }


def start_voice_call(
    business_id: int,
    *,
    call_sid: str,
    caller_number: str | None = None,
) -> int:
    with SessionLocal() as db:
        log = VoiceCallLog(
            business_id=business_id,
            call_sid=call_sid,
            caller_number=caller_number,
            started_at=datetime.utcnow(),
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log.id


def append_voice_call_transcript(call_log_id: int, role: str, text: str) -> None:
    cleaned = (text or "").strip()
    if not cleaned or not call_log_id:
        return

    prefix = "Caller" if role == "user" else "Assistant"
    line = f"{prefix}: {cleaned}"

    with SessionLocal() as db:
        log = db.query(VoiceCallLog).filter(VoiceCallLog.id == call_log_id).first()
        if not log:
            return
        existing = (log.transcript or "").strip()
        log.transcript = f"{existing}\n{line}".strip() if existing else line
        db.commit()


def end_voice_call(call_log_id: int) -> None:
    if not call_log_id:
        return

    with SessionLocal() as db:
        log = db.query(VoiceCallLog).filter(VoiceCallLog.id == call_log_id).first()
        if not log:
            return
        if not log.ended_at:
            log.ended_at = datetime.utcnow()
        db.commit()


def get_voice_call_history(business_id: int, limit: int = 50) -> list[dict]:
    safe_limit = min(max(limit, 1), 200)
    with SessionLocal() as db:
        logs = (
            db.query(VoiceCallLog)
            .filter(VoiceCallLog.business_id == business_id)
            .order_by(VoiceCallLog.started_at.desc())
            .limit(safe_limit)
            .all()
        )
        return [serialize_voice_call(log) for log in logs]
