"""In-memory store for temporary instant demo chatbot instances."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

DEFAULT_TTL_HOURS = 24


class DemoInstanceStore:
    def __init__(self, ttl_hours: int = DEFAULT_TTL_HOURS):
        self._ttl = timedelta(hours=ttl_hours)
        self._instances: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def _cleanup_expired(self) -> None:
        cutoff = datetime.utcnow() - self._ttl
        expired_ids = [
            instance_id
            for instance_id, record in self._instances.items()
            if record["created_at"] < cutoff
        ]
        for instance_id in expired_ids:
            self._instances.pop(instance_id, None)

    def create(self, *, prompt: str, business_data: dict) -> str:
        instance_id = str(uuid.uuid4())
        record = {
            "prompt": prompt,
            "businessData": business_data,
            "messages": [],
            "created_at": datetime.utcnow(),
            "createdAt": datetime.utcnow().isoformat() + "Z",
        }
        with self._lock:
            self._cleanup_expired()
            self._instances[instance_id] = record
        return instance_id

    def get(self, instance_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup_expired()
            record = self._instances.get(instance_id)
            if not record:
                return None
            return record

    def append_message(self, instance_id: str, role: str, content: str) -> None:
        with self._lock:
            record = self._instances.get(instance_id)
            if not record:
                return
            record["messages"].append({"role": role, "content": content})
