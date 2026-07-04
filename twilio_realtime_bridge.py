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

DEFAULT_REALTIME_MODEL = "gpt-realtime"
DEFAULT_REALTIME_MINI_MODEL = "gpt-realtime-mini"
DEPRECATED_REALTIME_MODEL_MARKERS = ("realtime-preview",)
DEFAULT_REALTIME_VOICE = "shimmer"
DEFAULT_REALTIME_TEMPERATURE = 0.8
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
    """TwiML for bidirectional Media Streams."""
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


def _resolve_realtime_model(configured: str) -> str:
    """Map deprecated preview model IDs to current GA Realtime models."""
    raw = configured.strip()
    if not raw:
        return DEFAULT_REALTIME_MODEL

    normalized = raw.lower()
    if any(marker in normalized for marker in DEPRECATED_REALTIME_MODEL_MARKERS):
        replacement = (
            DEFAULT_REALTIME_MINI_MODEL
            if "mini" in normalized
            else DEFAULT_REALTIME_MODEL
        )
        if normalized != replacement.lower():
            logger.warning(
                "REALTIME_MODEL=%s is deprecated or unavailable; using %s instead. "
                "Update REALTIME_MODEL on Render to avoid this warning.",
                raw,
                replacement,
            )
        return replacement

    return raw


def _realtime_model() -> str:
    configured = os.getenv("REALTIME_MODEL", DEFAULT_REALTIME_MODEL)
    return _resolve_realtime_model(configured)


def _realtime_voice() -> str:
    return os.getenv("REALTIME_VOICE", DEFAULT_REALTIME_VOICE).strip()


def _realtime_instructions() -> str:
    return os.getenv("REALTIME_INSTRUCTIONS", DEFAULT_INSTRUCTIONS).strip()


def _realtime_temperature() -> float:
    raw = os.getenv("REALTIME_TEMPERATURE", str(DEFAULT_REALTIME_TEMPERATURE))
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_REALTIME_TEMPERATURE


def _openai_realtime_uri() -> str:
    model = _realtime_model()
    temperature = _realtime_temperature()
    return f"wss://api.openai.com/v1/realtime?model={model}&temperature={temperature}"


def _openai_connect(uri: str, headers: dict[str, str]):
    """Return an OpenAI Realtime WebSocket context manager."""
    kwargs = {
        "ping_interval": 20,
        "ping_timeout": 20,
        "open_timeout": 20,
        "close_timeout": 10,
    }
    try:
        return websockets.connect(uri, additional_headers=headers, **kwargs)
    except TypeError:
        return websockets.connect(uri, extra_headers=headers, **kwargs)


async def _configure_openai_session(openai_ws: websockets.WebSocketClientProtocol) -> None:
    """Use GA Realtime session schema (audio/pcmu matches Twilio g711 ulaw)."""
    model = _realtime_model()
    session_update = {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": model,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "turn_detection": {"type": "server_vad"},
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": _realtime_voice(),
                },
            },
            "instructions": _realtime_instructions(),
        },
    }
    logger.info("Sending OpenAI session.update model=%s voice=%s", model, _realtime_voice())
    await openai_ws.send(json.dumps(session_update))


async def _request_initial_greeting(openai_ws: websockets.WebSocketClientProtocol) -> None:
    logger.info("Requesting initial AI greeting")
    await openai_ws.send(
        json.dumps(
            {
                "type": "response.create",
                "response": {
                    "output_modalities": ["audio"],
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


def _openai_ws_open(openai_ws: websockets.WebSocketClientProtocol) -> bool:
    state = getattr(openai_ws, "state", None)
    if state is None:
        return True
    state_name = getattr(state, "name", str(state))
    return state_name == "OPEN"


class StreamState:
    def __init__(self) -> None:
        self.stream_sid: str | None = None
        self.call_sid: str | None = None
        self.greeted = False
        self.pending_audio: list[str] = []


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

    await twilio_ws.send_json(
        {
            "event": "media",
            "streamSid": state.stream_sid,
            "media": {"payload": audio_chunk},
        }
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


async def _receive_from_twilio(
    twilio_ws: WebSocket,
    openai_ws: websockets.WebSocketClientProtocol,
    state: StreamState,
) -> None:
    try:
        async for message in twilio_ws.iter_text():
            payload = json.loads(message)
            event = payload.get("event")

            if event == "connected":
                logger.info("Twilio media stream connected")
                continue

            if event == "start":
                start = payload.get("start") or {}
                state.stream_sid = start.get("streamSid")
                state.call_sid = start.get("callSid")
                logger.info(
                    "Twilio media stream started streamSid=%s callSid=%s",
                    state.stream_sid,
                    state.call_sid,
                )
                await _flush_pending_audio(twilio_ws, state)
                if not state.greeted and _openai_ws_open(openai_ws):
                    state.greeted = True
                    await _request_initial_greeting(openai_ws)
                continue

            if event == "media" and _openai_ws_open(openai_ws):
                media = payload.get("media") or {}
                track = media.get("track")
                if track not in {None, "inbound", "inbound_track"}:
                    continue
                audio = media.get("payload")
                if audio:
                    await openai_ws.send(
                        json.dumps({"type": "input_audio_buffer.append", "audio": audio})
                    )
                continue

            if event == "stop":
                logger.info("Twilio media stream stopped streamSid=%s", state.stream_sid)
                break
    except WebSocketDisconnect:
        logger.info("Twilio WebSocket disconnected streamSid=%s", state.stream_sid)
        if _openai_ws_open(openai_ws):
            await openai_ws.close()
        raise


async def _send_to_twilio(
    twilio_ws: WebSocket,
    openai_ws: websockets.WebSocketClientProtocol,
    state: StreamState,
) -> None:
    try:
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
                    await twilio_ws.send_json(
                        {"event": "clear", "streamSid": state.stream_sid}
                    )
                if _openai_ws_open(openai_ws):
                    await openai_ws.send(json.dumps({"type": "response.cancel"}))
                continue

            audio_chunk = _audio_delta(event)
            if audio_chunk:
                await _send_audio_to_twilio(twilio_ws, state, audio_chunk)
                continue

            if event_type in {"response.done", "response.completed", "response.output_audio.done"}:
                logger.info("OpenAI response completed streamSid=%s", state.stream_sid)
    except websockets.ConnectionClosed as exc:
        logger.warning(
            "OpenAI Realtime WebSocket closed code=%s reason=%s",
            exc.code,
            exc.reason,
        )
    except Exception:
        logger.exception("Error while forwarding OpenAI audio to Twilio")


async def handle_twilio_openai_media_stream(twilio_ws: WebSocket) -> None:
    """Accept Twilio Media Stream and bridge audio with OpenAI Realtime."""
    await twilio_ws.accept()
    logger.info("Twilio /media WebSocket accepted")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY is not configured")
        return

    openai_uri = _openai_realtime_uri()
    headers = {"Authorization": f"Bearer {api_key}"}

    state = StreamState()

    try:
        async with _openai_connect(openai_uri, headers) as openai_ws:
            logger.info("Connected to OpenAI Realtime uri=%s", openai_uri)
            await _configure_openai_session(openai_ws)
            await asyncio.gather(
                _receive_from_twilio(twilio_ws, openai_ws, state),
                _send_to_twilio(twilio_ws, openai_ws, state),
            )
    except WebSocketDisconnect:
        logger.info("Twilio media call ended streamSid=%s", state.stream_sid)
    except websockets.ConnectionClosedError as exc:
        reason = exc.reason or ""
        if "model_not_found" in reason:
            configured = os.getenv("REALTIME_MODEL", DEFAULT_REALTIME_MODEL)
            logger.error(
                "OpenAI Realtime model not found (REALTIME_MODEL=%s). "
                "Set REALTIME_MODEL to gpt-realtime or gpt-realtime-mini on Render, "
                "or remove it to use the default. OpenAI reason: %s",
                configured,
                reason,
            )
        else:
            logger.exception(
                "OpenAI Realtime WebSocket closed during setup streamSid=%s callSid=%s",
                state.stream_sid,
                state.call_sid,
            )
    except Exception:
        logger.exception(
            "Twilio/OpenAI media bridge failed streamSid=%s callSid=%s",
            state.stream_sid,
            state.call_sid,
        )
    finally:
        logger.info(
            "Media stream bridge closed streamSid=%s callSid=%s",
            state.stream_sid,
            state.call_sid,
        )
