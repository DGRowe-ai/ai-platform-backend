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
    """TwiML for bidirectional Media Streams (Connect is required for AI audio playback)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{stream_url}"/>
  </Connect>
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


def _openai_connect(uri: str, headers: dict[str, str]):
    """Return an OpenAI Realtime WebSocket context manager."""
    try:
        return websockets.connect(
            uri,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=15,
        )
    except TypeError:
        return websockets.connect(
            uri,
            extra_headers=headers,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=15,
        )


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
                "silence_duration_ms": 700,
                "create_response": True,
                "interrupt_response": True,
            },
            "temperature": 0.8,
        },
    }
    await openai_ws.send(json.dumps(session_update))


async def _request_initial_greeting(openai_ws: websockets.WebSocketClientProtocol) -> None:
    logger.info("Requesting initial AI greeting")
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
    event_type = event.get("type")
    if event_type == "response.output_audio.delta":
        return event.get("delta")
    if event_type == "response.audio.delta":
        return event.get("delta")
    if event_type == "response.output_audio.done":
        return None
    return None


class StreamState:
    def __init__(self) -> None:
        self.stream_sid: str | None = None
        self.call_sid: str | None = None
        self.greeted = False
        self.pending_audio: list[str] = []
        self.ready = asyncio.Event()


async def _send_audio_to_twilio(
    twilio_ws: WebSocket,
    state: StreamState,
    audio_chunk: str,
) -> None:
    if twilio_ws.client_state != WebSocketState.CONNECTED:
        return

    if not state.stream_sid:
        state.pending_audio.append(audio_chunk)
        return

    await twilio_ws.send_text(
        json.dumps(
            {
                "event": "media",
                "streamSid": state.stream_sid,
                "media": {"payload": audio_chunk},
            }
        )
    )


async def _flush_pending_audio(twilio_ws: WebSocket, state: StreamState) -> None:
    if not state.stream_sid or not state.pending_audio:
        return

    logger.info(
        "Flushing %s buffered audio chunk(s) to Twilio streamSid=%s",
        len(state.pending_audio),
        state.stream_sid,
    )
    pending = state.pending_audio[:]
    state.pending_audio.clear()
    for chunk in pending:
        await _send_audio_to_twilio(twilio_ws, state, chunk)


async def _forward_twilio_to_openai(
    twilio_ws: WebSocket,
    openai_ws: websockets.WebSocketClientProtocol,
    state: StreamState,
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
            state.stream_sid = start.get("streamSid")
            state.call_sid = start.get("callSid")
            state.ready.set()
            logger.info(
                "Twilio media stream started streamSid=%s callSid=%s",
                state.stream_sid,
                state.call_sid,
            )
            await _flush_pending_audio(twilio_ws, state)

            if not state.greeted:
                state.greeted = True
                await _request_initial_greeting(openai_ws)
            continue

        if event == "media":
            media = payload.get("media") or {}
            track = media.get("track")
            if track not in {None, "inbound", "inbound_track"}:
                continue
            audio = media.get("payload")
            if not audio:
                continue
            await openai_ws.send(
                json.dumps({"type": "input_audio_buffer.append", "audio": audio})
            )
            continue

        if event == "stop":
            logger.info("Twilio media stream stopped streamSid=%s", state.stream_sid)
            break


async def _forward_openai_to_twilio(
    twilio_ws: WebSocket,
    openai_ws: websockets.WebSocketClientProtocol,
    state: StreamState,
) -> None:
    async for raw_message in openai_ws:
        event = json.loads(raw_message)
        event_type = event.get("type")

        if event_type == "error":
            logger.error("OpenAI Realtime error: %s", event.get("error"))
            continue

        if event_type in {"session.created", "session.updated"}:
            logger.info("OpenAI Realtime event: %s", event_type)
            continue

        if event_type == "input_audio_buffer.speech_started":
            if state.stream_sid and twilio_ws.client_state == WebSocketState.CONNECTED:
                await twilio_ws.send_text(
                    json.dumps({"event": "clear", "streamSid": state.stream_sid})
                )
            await openai_ws.send(json.dumps({"type": "response.cancel"}))
            continue

        audio_chunk = _audio_delta(event)
        if audio_chunk:
            await _send_audio_to_twilio(twilio_ws, state, audio_chunk)
            continue

        if event_type in {"response.done", "response.completed", "response.output_audio.done"}:
            logger.info("OpenAI response completed streamSid=%s", state.stream_sid)


async def handle_twilio_openai_media_stream(twilio_ws: WebSocket) -> None:
    """Accept Twilio Media Stream and bridge audio with OpenAI Realtime."""
    await twilio_ws.accept()
    logger.info("Twilio /media WebSocket accepted")

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

    state = StreamState()

    try:
        async with _openai_connect(openai_uri, headers) as openai_ws:
            logger.info("Connected to OpenAI Realtime model=%s", model)
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
            await asyncio.gather(*pending, return_exception=True)

            for task in done:
                exc = task.exception()
                if exc:
                    raise exc

    except WebSocketDisconnect:
        logger.info("Twilio media WebSocket disconnected")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Twilio/OpenAI media bridge failed")
        if twilio_ws.client_state == WebSocketState.CONNECTED:
            await twilio_ws.close(code=1011)
    finally:
        logger.info(
            "Media stream bridge closed streamSid=%s callSid=%s",
            state.stream_sid,
            state.call_sid,
        )
