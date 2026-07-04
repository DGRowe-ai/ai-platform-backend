"""Twilio voice webhook and media stream WebSocket endpoints."""

import logging

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["twilio"])

TWIML_TEST_MESSAGE = (
    "Hello from Rowe AI. Your voice webhook is connected successfully."
)


@router.post("/voice")
async def twilio_voice_webhook(request: Request):
    """Twilio voice webhook — returns TwiML for inbound/outbound call handling."""
    try:
        form = await request.form()
        call_sid = form.get("CallSid")
        if call_sid:
            logger.info("Twilio /voice webhook CallSid=%s", call_sid)
        else:
            logger.info("Twilio /voice webhook received")
    except Exception:
        logger.info("Twilio /voice webhook received (non-form payload)")

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">{TWIML_TEST_MESSAGE}</Say>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.websocket("/media")
async def twilio_media_stream(websocket: WebSocket):
    """Twilio Media Streams WebSocket — placeholder for future audio handling."""
    await websocket.accept()
    logger.info("Twilio Media Stream WebSocket connected")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Twilio Media Stream WebSocket disconnected")
