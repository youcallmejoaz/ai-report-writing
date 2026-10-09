"""Append-only, hash-chained audit log.

Each event's hash covers its own canonical content and the previous event's hash, so altering,
deleting or reordering any event breaks verification from that point on. In production the events are
written to PostgreSQL (INSERT-only grant, see ``db/schema.sql``) and streamed to a Blob container with a
time-based immutability policy; this in-memory implementation has the same chaining semantics.

Event ``details`` must not contain client personal data: record identifiers and hashes, not content.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.schemas import utcnow

GENESIS_HASH = "0" * 64


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class AuditEvent(BaseModel):
    seq: int
    at: datetime = Field(default_factory=utcnow)
    actor: str
    action: str
    object_type: str
    object_id: str
    case_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    hash: str = ""

    def compute_hash(self) -> str:
        body = self.model_dump(mode="json", exclude={"hash"})
        return sha256_hex(canonical_json(body))


class AuditLog:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(
        self,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        *,
        case_id: str | None = None,
        **details: Any,
    ) -> AuditEvent:
        prev = self._events[-1].hash if self._events else GENESIS_HASH
        event = AuditEvent(
            seq=len(self._events) + 1,
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            case_id=case_id,
            details=details,
            prev_hash=prev,
        )
        event.hash = event.compute_hash()
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    def for_case(self, case_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.case_id == case_id]


def verify_chain(events: list[AuditEvent] | tuple[AuditEvent, ...]) -> tuple[bool, int | None]:
    """Return (ok, seq_of_first_bad_event)."""
    prev = GENESIS_HASH
    for expected_seq, event in enumerate(events, start=1):
        if event.seq != expected_seq or event.prev_hash != prev or event.compute_hash() != event.hash:
            return False, event.seq
        prev = event.hash
    return True, None
