"""
Widget customization helpers.

Stores per-business widget appearance settings as JSON and validates
all user-provided values before they are saved or exposed publicly.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from models import WidgetSettings

HEX_COLOR_PATTERN = re.compile(r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")
ALLOWED_POSITIONS = {"bottom-right", "bottom-left", "top-right", "top-left"}
ALLOWED_SHAPES = {"rounded", "square", "circle"}

DEFAULT_WIDGET_SETTINGS: dict[str, Any] = {
    "primaryColor": "#4F46E5",
    "secondaryColor": "#FFFFFF",
    "chatBubbleColor": "#4F46E5",
    "textColor": "#000000",
    "welcomeMessage": "Hi there! How can I help you today?",
    "position": "bottom-right",
    "showAvatar": True,
    "avatarUrl": None,
    "widgetShape": "rounded",
    "fontFamily": "Inter",
    "customCSS": "",
    "enableShadow": True,
    "enableTypingAnimation": True,
}


class WidgetSettingsPayload(BaseModel):
    primaryColor: str = Field(default=DEFAULT_WIDGET_SETTINGS["primaryColor"])
    secondaryColor: str = Field(default=DEFAULT_WIDGET_SETTINGS["secondaryColor"])
    chatBubbleColor: str = Field(default=DEFAULT_WIDGET_SETTINGS["chatBubbleColor"])
    textColor: str = Field(default=DEFAULT_WIDGET_SETTINGS["textColor"])
    welcomeMessage: str = Field(default=DEFAULT_WIDGET_SETTINGS["welcomeMessage"])
    position: str = Field(default=DEFAULT_WIDGET_SETTINGS["position"])
    showAvatar: bool = Field(default=DEFAULT_WIDGET_SETTINGS["showAvatar"])
    avatarUrl: str | None = Field(default=None)
    widgetShape: str = Field(default=DEFAULT_WIDGET_SETTINGS["widgetShape"])
    fontFamily: str = Field(default=DEFAULT_WIDGET_SETTINGS["fontFamily"])
    customCSS: str = Field(default="")
    enableShadow: bool = Field(default=DEFAULT_WIDGET_SETTINGS["enableShadow"])
    enableTypingAnimation: bool = Field(default=DEFAULT_WIDGET_SETTINGS["enableTypingAnimation"])

    @field_validator(
        "primaryColor",
        "secondaryColor",
        "chatBubbleColor",
        "textColor",
    )
    @classmethod
    def validate_color(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not HEX_COLOR_PATTERN.match(normalized):
            raise ValueError("Colors must be valid hex values like #4F46E5")
        return normalized

    @field_validator("position")
    @classmethod
    def validate_position(cls, value: str) -> str:
        normalized = (value or "").strip()
        if normalized not in ALLOWED_POSITIONS:
            raise ValueError("Position must be bottom-right, bottom-left, top-right, or top-left")
        return normalized

    @field_validator("widgetShape")
    @classmethod
    def validate_shape(cls, value: str) -> str:
        normalized = (value or "").strip()
        if normalized not in ALLOWED_SHAPES:
            raise ValueError("Widget shape must be rounded, square, or circle")
        return normalized

    @field_validator("welcomeMessage")
    @classmethod
    def validate_welcome_message(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("Welcome message cannot be empty")
        if len(normalized) > 500:
            raise ValueError("Welcome message must be 500 characters or fewer")
        return normalized

    @field_validator("fontFamily")
    @classmethod
    def validate_font_family(cls, value: str) -> str:
        normalized = (value or "").strip() or DEFAULT_WIDGET_SETTINGS["fontFamily"]
        if len(normalized) > 100:
            raise ValueError("Font family must be 100 characters or fewer")
        if re.search(r"[<>]", normalized):
            raise ValueError("Font family contains invalid characters")
        return normalized

    @field_validator("customCSS")
    @classmethod
    def validate_custom_css(cls, value: str) -> str:
        normalized = (value or "").strip()
        if len(normalized) > 5000:
            raise ValueError("Custom CSS must be 5000 characters or fewer")
        if re.search(r"</?\s*script", normalized, re.IGNORECASE):
            raise ValueError("Custom CSS cannot include script tags")
        return normalized

    @field_validator("avatarUrl")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 500:
            raise ValueError("Avatar URL is too long")
        if not (
            normalized.startswith("https://")
            or normalized.startswith("http://")
            or normalized.startswith("/api/widget/avatar/")
        ):
            raise ValueError("Avatar URL must be an http(s) URL or uploaded widget avatar path")
        return normalized


def merge_with_defaults(raw_settings: dict[str, Any] | None) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_WIDGET_SETTINGS)
    if raw_settings:
        merged.update(raw_settings)
    return merged


def parse_settings_json(settings_json: str | None) -> dict[str, Any]:
    if not settings_json:
        return deepcopy(DEFAULT_WIDGET_SETTINGS)
    try:
        parsed = json.loads(settings_json)
    except (TypeError, json.JSONDecodeError):
        return deepcopy(DEFAULT_WIDGET_SETTINGS)
    if not isinstance(parsed, dict):
        return deepcopy(DEFAULT_WIDGET_SETTINGS)
    return merge_with_defaults(parsed)


def serialize_public_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Expose only widget appearance fields suitable for public embed scripts."""
    return {
        "primaryColor": settings["primaryColor"],
        "secondaryColor": settings["secondaryColor"],
        "chatBubbleColor": settings["chatBubbleColor"],
        "textColor": settings["textColor"],
        "welcomeMessage": settings["welcomeMessage"],
        "position": settings["position"],
        "showAvatar": settings["showAvatar"],
        "avatarUrl": settings["avatarUrl"],
        "widgetShape": settings["widgetShape"],
        "fontFamily": settings["fontFamily"],
        "customCSS": settings["customCSS"],
        "enableShadow": settings["enableShadow"],
        "enableTypingAnimation": settings["enableTypingAnimation"],
    }


def get_or_create_widget_settings(db: Session, business_id: int) -> WidgetSettings:
    record = (
        db.query(WidgetSettings)
        .filter(WidgetSettings.business_id == business_id)
        .first()
    )
    if record:
        return record

    record = WidgetSettings(
        business_id=business_id,
        settings_json=json.dumps(DEFAULT_WIDGET_SETTINGS),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_widget_settings_for_business(db: Session, business_id: int) -> dict[str, Any]:
    record = get_or_create_widget_settings(db, business_id)
    return parse_settings_json(record.settings_json)


def save_widget_settings_for_business(
    db: Session,
    business_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    validated = WidgetSettingsPayload.model_validate(payload).model_dump()
    record = get_or_create_widget_settings(db, business_id)
    record.settings_json = json.dumps(validated)
    db.add(record)
    db.commit()
    db.refresh(record)
    return parse_settings_json(record.settings_json)
