"""Instant demo API routes for Rowe AI marketing site."""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel, Field

from demo_instance_store import DemoInstanceStore
from demo_prompt_utils import generate_prompt, refine_business_data_with_openai
from demo_scraper import USER_AGENT, extract_business_data, validate_public_url

logger = logging.getLogger(__name__)

router = APIRouter()
demo_store = DemoInstanceStore()
openai_client = OpenAI()


class GenerateDemoRequest(BaseModel):
    url: str = Field(..., min_length=3, max_length=2048)


class DemoChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


async def fetch_website_html(url: str) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
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
        raise HTTPException(
            status_code=400,
            detail="Could not reach that website. Check the URL and try again.",
        ) from exc

    content_type = (response.headers.get("content-type") or "").lower()
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        raise HTTPException(status_code=400, detail="That URL does not appear to be a web page.")

    if len(response.content) > 2_000_000:
        raise HTTPException(status_code=400, detail="Website is too large to analyze for a demo.")

    return response.text


@router.post("/api/generate-demo")
async def generate_demo(req: GenerateDemoRequest):
    validated_url = validate_public_url(req.url)
    html = await fetch_website_html(validated_url)
    business_data = extract_business_data(html, validated_url)

    try:
        business_data = refine_business_data_with_openai(openai_client, business_data)
    except Exception:
        logger.exception("OpenAI business-data refinement failed for url=%s", validated_url)

    prompt = generate_prompt(business_data)
    instance_id = demo_store.create(prompt=prompt, business_data=business_data)

    return {
        "instanceId": instance_id,
        "prompt": prompt,
        "businessData": business_data,
    }


@router.post("/api/chat/{instance_id}")
async def demo_chat(instance_id: str, req: DemoChatRequest):
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
        except Exception as exc:
            logger.exception("Demo chat stream failed for instance_id=%s", instance_id)
            error_payload = json.dumps(
                {"error": "Sorry, the demo chatbot is unavailable right now. Please try again."}
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
