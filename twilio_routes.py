"""Twilio voice webhook and media stream WebSocket endpoints."""

import logging
import os

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import Response

from twilio_realtime_bridge import (
    build_unavailable_twiml,
    build_voice_twiml,
    get_media_stream_wss_url,
    handle_twilio_openai_media_stream,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twilio"])


@router.post("/voice")
async def twilio_voice_webhook(request: Request):
    """Twilio voice webhook — starts a Media Stream to /media for OpenAI Realtime."""
    try:
        form = await request.form()
        call_sid = form.get("CallSid")
        if call_sid:
            logger.info("Twilio /voice webhook CallSid=%s", call_sid)
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

    stream_url = get_media_stream_wss_url()
    logger.info("Starting Twilio media stream at %s", stream_url)
    twiml = build_voice_twiml(stream_url)
    return Response(content=twiml, media_type="application/xml")


@router.websocket("/media")
async def twilio_media_stream(websocket: WebSocket):
    """Twilio Media Streams WebSocket bridged to OpenAI Realtime API."""
    await handle_twilio_openai_media_stream(websocket)
