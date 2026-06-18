"""Instant demo API routes for Rowe AI marketing site."""

from __future__ import annotations

import json
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from demo_instance_store import DemoInstanceStore
from demo_prompt_utils import generate_prompt, refine_business_data_with_openai
from demo_scraper import USER_AGENT, extract_business_data, validate_public_url

logger = logging.getLogger(__name__)

router = APIRouter()
demo_store = DemoInstanceStore()


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Demo generation is temporarily unavailable. Please try again later.",
        )
    return OpenAI(api_key=api_key)


class GenerateDemoRequest(BaseModel):
    url: str = Field(..., min_length=3, max_length=2048)


class DemoChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


async def fetch_website_html(url: str) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    response = None
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not fetch website (HTTP {exc.response.status_code}).",
        ) from exc
    except httpx.RequestError as exc:
        logger.warning("Website fetch failed for url=%s: %s", url, exc)
        raise HTTPException(
            status_code=400,
            detail="Could not reach that website. Check the URL and try again.",
        ) from exc

    if response is None:
        raise HTTPException(status_code=400, detail="Could not fetch website content.")

    content_type = (response.headers.get("content-type") or "").lower()
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise HTTPException(status_code=400, detail="That URL does not appear to be a web page.")

    if len(response.content) > 2_000_000:
        raise HTTPException(status_code=400, detail="Website is too large to analyze for a demo.")

    return response.text


@router.post("/api/generate-demo")
async def generate_demo(req: GenerateDemoRequest):
    try:
        logger.info("generate-demo started url=%s", req.url)

        validated_url = validate_public_url(req.url)
        html = await fetch_website_html(validated_url)
        business_data = extract_business_data(html, validated_url)

        try:
            business_data = refine_business_data_with_openai(
                get_openai_client(),
                business_data,
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception(
                "OpenAI business-data refinement failed for url=%s",
                validated_url,
            )

        prompt = generate_prompt(business_data)
        instance_id = demo_store.create(prompt=prompt, business_data=business_data)

        logger.info(
            "generate-demo completed url=%s instance_id=%s business=%s",
            validated_url,
            instance_id,
            business_data.get("name"),
        )

        return {
            "instanceId": instance_id,
            "prompt": prompt,
            "businessData": business_data,
        }
    except HTTPException:
        raise
    except ValidationError as exc:
        logger.warning("generate-demo validation error: %s", exc)
        raise HTTPException(status_code=422, detail="Invalid request body.") from exc
    except Exception as exc:
        logger.exception("generate-demo failed url=%s", getattr(req, "url", ""))
        raise HTTPException(
            status_code=500,
            detail="Unable to generate demo right now. Please try again.",
        ) from exc


@router.post("/api/chat/{instance_id}")
async def demo_chat(instance_id: str, req: DemoChatRequest):
    try:
        record = demo_store.get(instance_id)
        if not record:
            raise HTTPException(status_code=404, detail="Demo session expired or not found.")

        user_message = req.message.strip()
        if not user_message:
            raise HTTPException(status_code=400, detail="Message cannot be empty.")

        demo_store.append_message(instance_id, "user", user_message)
        record = demo_store.get(instance_id)
        if not record:
            raise HTTPException(status_code=404, detail="Demo session expired or not found.")

        conversation = [{"role": "system", "content": record["prompt"]}]
        conversation.extend(record["messages"])

        openai_client = get_openai_client()

        async def event_stream():
            assistant_chunks: list[str] = []
            try:
                stream = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=conversation,
                    stream=True,
                    max_tokens=350,
                    temperature=0.4,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if not delta:
                        continue
                    assistant_chunks.append(delta)
                    payload = json.dumps({"content": delta})
                    yield f"data: {payload}\n\n"
            except Exception:
                logger.exception("Demo chat stream failed for instance_id=%s", instance_id)
                error_payload = json.dumps(
                    {
                        "error": (
                            "Sorry, the demo chatbot is unavailable right now. "
                            "Please try again."
                        )
                    }
                )
                yield f"data: {error_payload}\n\n"
                yield "data: [DONE]\n\n"
                return

            assistant_reply = "".join(assistant_chunks).strip()
            if assistant_reply:
                demo_store.append_message(instance_id, "assistant", assistant_reply)

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("demo_chat failed instance_id=%s", instance_id)
        raise HTTPException(
            status_code=500,
            detail="Demo chat failed. Please try again.",
        ) from exc


@router.get("/api/demo-health")
async def demo_health():
    return {
        "status": "ok",
        "routes": {
            "generateDemo": "POST /api/generate-demo",
            "chat": "POST /api/chat/{instanceId}",
        },
    }
