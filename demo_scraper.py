"""Scrape and extract business information from a public website HTML page."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from fastapi import HTTPException

USER_AGENT = "RoweAI-InstantDemo/1.0 (+https://roweai.ca/instant-demo)"
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"}
SECTION_KEYWORDS = {
    "services": ("service", "what we do", "our work", "offerings", "solutions"),
    "about": ("about", "who we are", "our story", "mission"),
    "contact": ("contact", "get in touch", "reach us", "location"),
    "hours": ("hours", "opening", "open", "schedule"),
    "faq": ("faq", "frequently asked", "questions"),
}


def validate_public_url(url: str) -> str:
    """Normalize and validate a user-supplied website URL."""
    cleaned = (url or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Please enter a website URL.")

    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"

    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="URL must use http or https.")

    host = (parsed.hostname or "").lower()
    if not host or host in BLOCKED_HOSTS or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="Please enter a valid public website URL.")

    try:
        resolved_ip = ipaddress.ip_address(socket.gethostbyname(host))
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="Could not resolve that website URL.") from exc

    if resolved_ip.is_private or resolved_ip.is_loopback or resolved_ip.is_link_local:
        raise HTTPException(status_code=400, detail="Please enter a public website URL.")

    return cleaned


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _split_bullet_lines(text: str) -> list[str]:
    lines = []
    for raw_line in re.split(r"[\n\r•·|]+", text):
        line = _clean_text(raw_line)
        if len(line) >= 3:
            lines.append(line)
    return lines


def _collect_section_text(heading) -> str:
    chunks: list[str] = []
    for sibling in heading.find_next_siblings():
        if sibling.name in {"h1", "h2", "h3", "h4"}:
            break
        chunks.append(sibling.get_text(" ", strip=True))
        if len(_clean_text(" ".join(chunks))) > 1200:
            break
    return _clean_text(" ".join(chunks))


def _first_heading_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["h1", "h2"]):
        text = _clean_text(tag.get_text())
        if 2 <= len(text) <= 120:
            return text
    return ""


def extract_business_data(html: str, source_url: str = "") -> dict:
    """Parse HTML and return structured business data for demo generation."""
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title_text = _clean_text(soup.title.get_text()) if soup.title else ""
    meta_description = ""
    meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if meta_tag and meta_tag.get("content"):
        meta_description = _clean_text(meta_tag["content"])

    og_name = soup.find("meta", property="og:site_name")
    og_site_name = _clean_text(og_name["content"]) if og_name and og_name.get("content") else ""

    name = og_site_name or _first_heading_text(soup)
    if not name and title_text:
        name = _clean_text(re.split(r"[|\-–—]", title_text)[0])
    if not name:
        host = urlparse(source_url).hostname or "Business"
        name = host.replace("www.", "").split(".")[0].replace("-", " ").title()

    description = meta_description
    services: list[str] = []
    hours = ""
    contact = ""
    faqs: list[str] = []
    about = ""

    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        heading_text = _clean_text(heading.get_text()).lower()
        if not heading_text:
            continue

        section_text = _collect_section_text(heading)
        if not section_text:
            continue

        if any(keyword in heading_text for keyword in SECTION_KEYWORDS["services"]):
            services.extend(_split_bullet_lines(section_text))
            for sibling in heading.find_next_siblings():
                if sibling.name in {"h1", "h2", "h3", "h4"}:
                    break
                for li in sibling.find_all("li"):
                    line = _clean_text(li.get_text())
                    if 3 <= len(line) <= 120:
                        services.append(line)
        elif any(keyword in heading_text for keyword in SECTION_KEYWORDS["about"]):
            about = section_text if len(section_text) > len(about) else about
        elif any(keyword in heading_text for keyword in SECTION_KEYWORDS["contact"]):
            contact = section_text if len(section_text) > len(contact) else contact
        elif any(keyword in heading_text for keyword in SECTION_KEYWORDS["hours"]):
            hours = section_text if len(section_text) > len(hours) else hours
        elif any(keyword in heading_text for keyword in SECTION_KEYWORDS["faq"]):
            faqs.extend(_split_bullet_lines(section_text))

    if not description:
        description = about[:500] if about else _clean_text(soup.get_text(" ", strip=True))[:500]

    if not services:
        for li in soup.find_all("li")[:12]:
            line = _clean_text(li.get_text())
            if 4 <= len(line) <= 120:
                services.append(line)

    services = list(dict.fromkeys(services))[:12]
    faqs = list(dict.fromkeys(faqs))[:8]

    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html)
    phones = re.findall(r"(?:\+?\d[\d\s().-]{7,}\d)", html)
    if not contact and (emails or phones):
        contact_parts = []
        if emails:
            contact_parts.append(emails[0])
        if phones:
            contact_parts.append(phones[0])
        contact = " | ".join(contact_parts)

    return {
        "name": name,
        "description": description,
        "services": services,
        "hours": hours,
        "contact": contact,
        "faqs": faqs,
        "source_url": source_url,
    }
