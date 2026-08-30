from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from funduq_provider_sdk.protocol.frames import Frame, Malformed, WireFrame

_FRAMES: TypeAdapter[Any] = TypeAdapter(WireFrame)


def encode(frame: Frame) -> dict[str, Any]:
    """The wire form of `frame`."""
    return frame.model_dump(mode="json", by_alias=True)


def decode(payload: Any, *, frames: TypeAdapter[Any] | None = None) -> Frame:
    """The frame `payload` is, or a `Malformed` carrying why it is not one."""
    try:
        return (frames or _FRAMES).validate_python(payload)
    except ValidationError as exc:
        return Malformed(id=_id_of(payload), reason=str(exc))


def _id_of(payload: Any) -> str | None:
    """The correlation id of something that did not decode, if it has one."""
    if isinstance(payload, dict):
        value = payload.get("id")
        if isinstance(value, str):
            return value
    return None
