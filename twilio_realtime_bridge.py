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


def build_voice_twiml(
    stream_url: str,
    *,
    business_id: int | None = None,
    caller_number: str | None = None,
) -> str:
    """TwiML for bidirectional Media Streams."""
    parameters = ""
    if business_id is not None:
        parameters += f'      <Parameter name="business_id" value="{business_id}"/>\n'
    if caller_number:
        safe_caller = caller_number.replace('"', "")
        parameters += f'      <Parameter name="caller" value="{safe_caller}"/>\n'

    stream_body = f'    <Stream url="{stream_url}">\n{parameters}    </Stream>'
    if not parameters:
        stream_body = f'    <Stream url="{stream_url}"/>'

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
{stream_body}
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


async def _configure_openai_session(
    openai_ws: websockets.WebSocketClientProtocol,
    instructions: str | None = None,
) -> None:
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
                    "transcription": {"model": "gpt-4o-mini-transcribe"},
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": _realtime_voice(),
                },
            },
            "instructions": instructions or _realtime_instructions(),
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
        self.business_id: int | None = None
        self.caller_number: str | None = None
        self.call_log_id: int | None = None
        self.greeted = False
        self.pending_audio: list[str] = []
        self.instructions: str | None = None


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


def _transcript_from_event(event: dict[str, Any]) -> tuple[str, str] | None:
    event_type = event.get("type", "")

    if event_type in {
        "conversation.item.input_audio_transcription.completed",
        "input_audio_transcription.completed",
    }:
        transcript = event.get("transcript")
        if not transcript:
            item = event.get("item") or {}
            transcript = item.get("transcript")
            if not transcript:
                for part in item.get("content") or []:
                    if isinstance(part, dict):
                        transcript = part.get("transcript") or part.get("text")
                        if transcript:
                            break
        if transcript:
            return "user", str(transcript).strip()

    if event_type == "conversation.item.done":
        item = event.get("item") or {}
        if (item.get("role") or "").strip().lower() == "user":
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                transcript = part.get("transcript") or part.get("text")
                if transcript:
                    return "user", str(transcript).strip()

    if event_type in {
        "response.audio_transcript.done",
        "response.output_audio_transcript.done",
        "response.output_audio_transcript.completed",
    }:
        transcript = event.get("transcript")
        if transcript:
            return "assistant", str(transcript).strip()

    if event_type == "response.done":
        response = event.get("response") or {}
        for item in response.get("output") or []:
            if not isinstance(item, dict):
                continue
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                transcript = part.get("transcript") or part.get("text")
                if transcript:
                    return "assistant", str(transcript).strip()

    return None


def _load_business_voice_instructions(business_id: int | None) -> str | None:
    if not business_id:
        return None

    try:
        from database import SessionLocal
        from knowledge_utils import retrieve_voice_knowledge_context
        from models import Business, BusinessSettings, User
        from plan_utils import user_tier
        from voice_settings_utils import build_voice_realtime_instructions

        with SessionLocal() as db:
            settings = (
                db.query(BusinessSettings).filter_by(business_id=business_id).first()
            )
            if not settings:
                logger.warning("No business_settings row for business_id=%s", business_id)
                return None
            business = db.query(Business).filter(Business.id == business_id).first()
            tier = None
            if business and business.owner_id:
                owner = db.query(User).filter(User.id == business.owner_id).first()
                if owner:
                    tier = user_tier(owner)
            knowledge_context = retrieve_voice_knowledge_context(db, business_id)
            instructions = build_voice_realtime_instructions(
                settings,
                knowledge_context,
                business_name=(business.name if business else ""),
                tier=tier,
            )
            logger.info(
                "Loaded voice instructions business_id=%s tier=%s custom_chars=%s knowledge_chars=%s total_chars=%s",
                business_id,
                tier,
                len((settings.voice_custom_instructions or "").strip()),
                len(knowledge_context),
                len(instructions),
            )
            return instructions
    except Exception:
        logger.exception("Unable to load voice instructions for business_id=%s", business_id)
        return None


async def _apply_business_voice_session(
    openai_ws: websockets.WebSocketClientProtocol,
    state: StreamState,
) -> bool:
    """Load business settings into the OpenAI session once Twilio identifies the business."""
    if not state.business_id:
        return False

    instructions = _load_business_voice_instructions(state.business_id)
    if not instructions:
        return False

    state.instructions = instructions
    await _configure_openai_session(openai_ws, instructions)
    return True


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
                custom = start.get("customParameters") or {}
                business_raw = custom.get("business_id")
                if business_raw:
                    try:
                        state.business_id = int(business_raw)
                    except (TypeError, ValueError):
                        logger.warning("Invalid business_id parameter=%s", business_raw)
                state.caller_number = custom.get("caller") or state.caller_number
                logger.info(
                    "Twilio media stream started streamSid=%s callSid=%s businessId=%s",
                    state.stream_sid,
                    state.call_sid,
                    state.business_id,
                )
                if state.business_id and state.call_sid:
                    try:
                        from voice_call_utils import start_voice_call

                        state.call_log_id = start_voice_call(
                            state.business_id,
                            call_sid=state.call_sid,
                            caller_number=state.caller_number,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to create voice call log business_id=%s",
                            state.business_id,
                        )
                await _flush_pending_audio(twilio_ws, state)

                if state.business_id and _openai_ws_open(openai_ws):
                    applied = await _apply_business_voice_session(openai_ws, state)
                    if not applied:
                        logger.warning(
                            "Voice settings were not applied for business_id=%s",
                            state.business_id,
                        )

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

            transcript_entry = _transcript_from_event(event)
            if transcript_entry and state.call_log_id:
                role, text = transcript_entry
                try:
                    from voice_call_utils import append_voice_call_transcript

                    append_voice_call_transcript(state.call_log_id, role, text)
                except Exception:
                    logger.exception("Failed to append voice transcript call_log_id=%s", state.call_log_id)

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


async def handle_twilio_openai_media_stream(
    twilio_ws: WebSocket,
    *,
    business_id: int | None = None,
    caller_number: str | None = None,
) -> None:
    """Accept Twilio Media Stream and bridge audio with OpenAI Realtime."""
    await twilio_ws.accept()
    logger.info("Twilio /media WebSocket accepted business_id=%s", business_id)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY is not configured")
        return

    openai_uri = _openai_realtime_uri()
    headers = {"Authorization": f"Bearer {api_key}"}

    state = StreamState()
    state.business_id = business_id
    state.caller_number = caller_number

    try:
        async with _openai_connect(openai_uri, headers) as openai_ws:
            logger.info("Connected to OpenAI Realtime uri=%s", openai_uri)
            bootstrap_instructions = (
                _load_business_voice_instructions(business_id)
                if business_id
                else None
            )
            await _configure_openai_session(openai_ws, bootstrap_instructions)
            state.instructions = bootstrap_instructions
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
        if state.call_log_id:
            try:
                from voice_call_utils import end_voice_call

                end_voice_call(state.call_log_id)
            except Exception:
                logger.exception("Failed to finalize voice call log id=%s", state.call_log_id)
        logger.info(
            "Media stream bridge closed streamSid=%s callSid=%s",
            state.stream_sid,
            state.call_sid,
        )
