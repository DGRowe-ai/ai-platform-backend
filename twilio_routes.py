"""Twilio voice webhook and media stream WebSocket endpoints."""

import logging
import os

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import Response

from database import SessionLocal
from twilio_realtime_bridge import (
    build_unavailable_twiml,
    build_voice_twiml,
    get_media_stream_wss_url,
    handle_twilio_openai_media_stream,
)
from voice_business_utils import find_business_for_inbound_call

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twilio"])


@router.post("/voice")
async def twilio_voice_webhook(request: Request):
    """Twilio voice webhook — starts a Media Stream to /media for OpenAI Realtime."""
    call_sid = None
    caller_number = None
    to_number = None

    try:
        form = await request.form()
        call_sid = form.get("CallSid")
        caller_number = form.get("From")
        to_number = form.get("To")
        if call_sid:
            logger.info(
                "Twilio /voice webhook CallSid=%s From=%s To=%s",
                call_sid,
                caller_number,
                to_number,
            )
        else:
            logger.info("Twilio /voice webhook received")
    except Exception:
        logger.info("Twilio /voice webhook received (non-form payload)")

    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY missing; returning unavailable TwiML")
        twiml = build_unavailable_twiml(
            "We're sorry, the voice assistant is temporarily unavailable. Please try again later."
        )
        return Response(content=twiml, media_type="application/xml")

    business_id = None
    with SessionLocal() as db:
        business = find_business_for_inbound_call(db, to_number)
        if business:
            business_id = business.id
            logger.info(
                "Routing voice call to business_id=%s folder=%s",
                business.id,
                business.folder_name,
            )

    stream_url = get_media_stream_wss_url()
    logger.info("Starting Twilio media stream at %s", stream_url)
    twiml = build_voice_twiml(
        stream_url,
        business_id=business_id,
        caller_number=caller_number,
    )
    return Response(content=twiml, media_type="application/xml")


@router.websocket("/media")
async def twilio_media_stream(websocket: WebSocket):
    """Twilio Media Streams WebSocket bridged to OpenAI Realtime API."""
    await handle_twilio_openai_media_stream(websocket)
