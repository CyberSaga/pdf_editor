from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SessionTransferPayload:
    snapshot_bytes: bytes = field(repr=False)
    source_path: str
    saved_path: str | None
    display_name: str
    dirty: bool
    current_page: int
    scale: float
    color_profile: str
    password: str | None = field(default=None, repr=False)
    auth_level: int | None = None

    @classmethod
    def from_model(
        cls,
        model,
        session_id: str | None,
        *,
        current_page: int,
        scale: float,
        color_profile: str,
    ) -> SessionTransferPayload:
        if not session_id or model.get_active_session_id() != session_id:
            raise ValueError("the transferred session must be active")
        session = model._sessions_by_id[session_id]
        dirty = bool(
            model.session_has_unsaved_changes(session_id)
            or session.edit_count
            or session.pending_edits
        )
        return cls(
            snapshot_bytes=model.capture_worker_snapshot_bytes(),
            source_path=session.original_path,
            saved_path=session.saved_path,
            display_name=session.display_name,
            dirty=dirty,
            current_page=max(0, int(current_page)),
            scale=max(0.1, float(scale)),
            color_profile=str(color_profile),
            password=session.password,
            auth_level=session.auth_level,
        )
