"""Bridge Twilio Media Streams with the OpenAI Realtime API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

DEFAULT_REALTIME_MODEL = "gpt-4o-realtime-preview-2024-12-17"
DEFAULT_REALTIME_VOICE = "shimmer"
DEFAULT_INSTRUCTIONS = (
    "You are a friendly, natural-sounding voice assistant for Rowe AI. "
    "Help callers with questions about AI chatbots and customer support automation. "
    "Keep answers concise and conversational for phone calls. "
    "When the call begins, greet the caller warmly and ask how you can help."
)


def get_media_stream_wss_url() -> str:
    """Build the public wss:// URL Twilio uses for Media Streams."""
    base = (
        os.getenv("BACKEND_PUBLIC_URL")
        or os.getenv("PUBLIC_BACKEND_URL")
        or "https://ai-platform-backend-ulqs.onrender.com"
    ).rstrip("/")

    if base.startswith("https://"):
        host = base[len("https://") :]
        return f"wss://{host}/media"
    if base.startswith("http://"):
        host = base[len("http://") :]
        return f"ws://{host}/media"
    if base.startswith("wss://") or base.startswith("ws://"):
        return f"{base}/media"
    return f"wss://{base}/media"


def build_voice_twiml(stream_url: str) -> str:
    """TwiML that starts a Media Stream and keeps the call open."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Start>
    <Stream url="{stream_url}" track="inbound_track"/>
  </Start>
  <Pause length="3600"/>
</Response>"""


def build_unavailable_twiml(message: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Joanna">{message}</Say>
</Response>"""


def _realtime_model() -> str:
    return os.getenv("REALTIME_MODEL", DEFAULT_REALTIME_MODEL).strip()


def _realtime_voice() -> str:
    return os.getenv("REALTIME_VOICE", DEFAULT_REALTIME_VOICE).strip()


def _realtime_instructions() -> str:
    return os.getenv("REALTIME_INSTRUCTIONS", DEFAULT_INSTRUCTIONS).strip()


async def _configure_openai_session(openai_ws: websockets.WebSocketClientProtocol) -> None:
    session_update = {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": _realtime_instructions(),
            "voice": _realtime_voice(),
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
                "create_response": True,
                "interrupt_response": True,
            },
            "temperature": 0.8,
        },
    }
    await openai_ws.send(json.dumps(session_update))


async def _request_initial_greeting(openai_ws: websockets.WebSocketClientProtocol) -> None:
    await openai_ws.send(
        json.dumps(
            {
                "type": "response.create",
                "response": {
                    "modalities": ["audio", "text"],
                },
            }
        )
    )


def _audio_delta(event: dict[str, Any]) -> str | None:
    if event.get("type") == "response.output_audio.delta":
        return event.get("delta")
    if event.get("type") == "response.audio.delta":
        return event.get("delta")
    return None


async def _forward_twilio_to_openai(
    twilio_ws: WebSocket,
    openai_ws: websockets.WebSocketClientProtocol,
    state: dict[str, str | None],
) -> None:
    while True:
        message = await twilio_ws.receive_text()
        payload = json.loads(message)
        event = payload.get("event")

        if event == "connected":
            logger.info("Twilio media stream connected")
            continue

        if event == "start":
            start = payload.get("start") or {}
            state["stream_sid"] = start.get("streamSid")
            state["call_sid"] = start.get("callSid")
            logger.info(
                "Twilio media stream started streamSid=%s callSid=%s",
                state.get("stream_sid"),
                state.get("call_sid"),
            )
            continue

        if event == "media":
            media = payload.get("media") or {}
            if media.get("track") not in {None, "inbound", "inbound_track"}:
                continue
            audio = media.get("payload")
            if not audio:
                continue
            await openai_ws.send(
                json.dumps({"type": "input_audio_buffer.append", "audio": audio})
            )
            continue

        if event == "stop":
            logger.info("Twilio media stream stopped streamSid=%s", state.get("stream_sid"))
            break


async def _forward_openai_to_twilio(
    twilio_ws: WebSocket,
    openai_ws: websockets.WebSocketClientProtocol,
    state: dict[str, str | None],
) -> None:
    async for raw_message in openai_ws:
        event = json.loads(raw_message)
        event_type = event.get("type")

        if event_type == "error":
            logger.error("OpenAI Realtime error: %s", event.get("error"))
            continue

        if event_type in {"session.created", "session.updated"}:
            if event_type == "session.updated" and not state.get("greeted"):
                state["greeted"] = True
                await _request_initial_greeting(openai_ws)
            continue

        if event_type == "input_audio_buffer.speech_started":
            stream_sid = state.get("stream_sid")
            if stream_sid and twilio_ws.client_state == WebSocketState.CONNECTED:
                await twilio_ws.send_text(
                    json.dumps({"event": "clear", "streamSid": stream_sid})
                )
            await openai_ws.send(json.dumps({"type": "response.cancel"}))
            continue

        audio_chunk = _audio_delta(event)
        if audio_chunk:
            stream_sid = state.get("stream_sid")
            if stream_sid and twilio_ws.client_state == WebSocketState.CONNECTED:
                await twilio_ws.send_text(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": audio_chunk},
                        }
                    )
                )
            continue

        if event_type in {"response.done", "response.completed"}:
            logger.debug("OpenAI response completed for streamSid=%s", state.get("stream_sid"))


async def handle_twilio_openai_media_stream(twilio_ws: WebSocket) -> None:
    """Accept Twilio Media Stream and bridge audio with OpenAI Realtime."""
    await twilio_ws.accept()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY is not configured; closing media stream")
        await twilio_ws.close(code=1011)
        return

    model = _realtime_model()
    openai_uri = f"wss://api.openai.com/v1/realtime?model={model}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    state: dict[str, str | None] = {"stream_sid": None, "call_sid": None, "greeted": False}

    try:
        async with websockets.connect(
            openai_uri,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=15,
        ) as openai_ws:
            await _configure_openai_session(openai_ws)

            twilio_task = asyncio.create_task(
                _forward_twilio_to_openai(twilio_ws, openai_ws, state)
            )
            openai_task = asyncio.create_task(
                _forward_openai_to_twilio(twilio_ws, openai_ws, state)
            )

            done, pending = await asyncio.wait(
                {twilio_task, openai_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            for task in done:
                if task.exception():
                    raise task.exception()

    except WebSocketDisconnect:
        logger.info("Twilio media WebSocket disconnected")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Twilio/OpenAI media bridge failed")
        if twilio_ws.client_state == WebSocketState.CONNECTED:
            await twilio_ws.close(code=1011)
    finally:
        logger.info("Media stream bridge closed streamSid=%s", state.get("stream_sid"))
