"""Protocol models shared by the print helper subprocess."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base_driver import PrintJobOptions


@dataclass
class PrintHelperJob:
    """Immutable job payload handed to the helper subprocess."""

    job_id: str
    input_pdf_path: str
    watermarks: list[dict]
    options: PrintJobOptions
    heartbeat_interval_ms: int = 5000
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        normalized = self.options.normalized()
        options_payload = {
            name: getattr(normalized, name)
            for name in normalized.__dataclass_fields__
        }
        options_payload["override_fields"] = sorted(normalized.override_fields)
        return {
            "job_id": self.job_id,
            "input_pdf_path": self.input_pdf_path,
            "watermarks": list(self.watermarks),
            "options": options_payload,
            "heartbeat_interval_ms": int(self.heartbeat_interval_ms),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> "PrintHelperJob":
        options_payload = dict(payload.get("options") or {})
        override_fields = set(options_payload.get("override_fields") or set())
        options_payload["override_fields"] = override_fields
        return cls(
            job_id=str(payload["job_id"]),
            input_pdf_path=str(payload["input_pdf_path"]),
            watermarks=list(payload.get("watermarks") or []),
            options=PrintJobOptions(**options_payload),
            heartbeat_interval_ms=int(payload.get("heartbeat_interval_ms", 5000)),
            metadata=dict(payload.get("metadata") or {}),
        )

    @classmethod
    def read(cls, path: str | Path) -> "PrintHelperJob":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_json_dict(payload)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False),
            encoding="utf-8",
        )


def encode_helper_event(job_id: str, event: str, message: str = "", **payload: Any) -> dict[str, Any]:
    out = {
        "job_id": job_id,
        "event": event,
        "message": message,
    }
    out.update(payload)
    return out


def parse_helper_event(raw_line: str) -> dict[str, Any]:
    return json.loads(raw_line)
