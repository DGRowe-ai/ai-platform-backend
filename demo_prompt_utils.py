"""Prompt generation helpers for instant demo chatbots."""

from __future__ import annotations

import json


def generate_prompt(business_data: dict) -> str:
    """Build the system prompt for a personalized demo chatbot."""
    payload = {
        "name": business_data.get("name") or "This Business",
        "description": business_data.get("description") or "",
        "services": business_data.get("services") or [],
        "hours": business_data.get("hours") or "",
        "contact": business_data.get("contact") or "",
        "faqs": business_data.get("faqs") or [],
        "source_url": business_data.get("source_url") or "",
    }
    business_name = payload["name"]
    business_json = json.dumps(payload, indent=2)

    return f"""You are a customer service chatbot for {business_name}.
Here is the business information extracted from their website:
{business_json}

Your job is to answer customer questions, provide information, and help users understand the business.
Keep responses short, friendly, and helpful.
If you do not know something that is not in the business information, say you do not have that detail and suggest contacting the business directly.
Do not invent prices, policies, or guarantees that are not supported by the provided information."""


def refine_business_data_with_openai(client, business_data: dict) -> dict:
    """Use OpenAI to normalize sparse scraped content into structured JSON."""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You clean up scraped website data for a chatbot demo. "
                    "Return valid JSON with keys: name, description, services, hours, contact, faqs. "
                    "services and faqs must be arrays of strings. Keep facts grounded in the input."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(business_data),
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=700,
        temperature=0.2,
    )

    content = response.choices[0].message.content or "{}"
    refined = json.loads(content)

    merged = dict(business_data)
    for key in ("name", "description", "hours", "contact"):
        if refined.get(key):
            merged[key] = refined[key]
    if isinstance(refined.get("services"), list) and refined["services"]:
        merged["services"] = [str(item).strip() for item in refined["services"] if str(item).strip()][:12]
    if isinstance(refined.get("faqs"), list) and refined["faqs"]:
        merged["faqs"] = [str(item).strip() for item in refined["faqs"] if str(item).strip()][:8]

    return merged
