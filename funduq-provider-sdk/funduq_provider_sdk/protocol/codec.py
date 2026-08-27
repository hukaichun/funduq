from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from funduq_provider_sdk.protocol.frames import Frame, Malformed, WireFrame

_FRAMES: TypeAdapter[Any] = TypeAdapter(WireFrame)


def encode(frame: Frame) -> dict[str, Any]:
    """The wire form of `frame`.

    **No `exclude_none` here**, and that is not an oversight. The relay uses
    the flag everywhere it dumps a typed *event*, because a default dump
    injects `timestamp: null` and `rawEvent: null` into a caller's stream. But
    a frame nests `DeliveredRun`, whose published form is
    `model_dump(by_alias=True)` — the one `docs/contract-vectors.json` pins —
    and `RunAgentInput` has required fields that are legitimately `None`.
    Dropping them yields an envelope the far side cannot rebuild, so a
    perfectly good run comes back as a permanent refusal.

    The flag belongs to the event dump, in `ProviderSide.report`, and nowhere
    else. Two rules that lived in different paragraphs of
    `writing-a-transport.md` and never met until one function had to do both.
    """
    return frame.model_dump(mode="json", by_alias=True)


def decode(payload: Any, *, frames: TypeAdapter[Any] | None = None) -> Frame:
    """The frame `payload` is, or a `Malformed` carrying why it is not one.

    Decoding never raises and never answers. A codec that replied on its own
    would be making a protocol decision from outside the machine — exactly the
    split this package closes — so a failure becomes an ordinary input and the
    transition table decides.

    `frames` overrides the vocabulary. An agent link and an LLM link are
    different connections to different rosters, so each has its own set —
    two codecs is the shape of the thing, not a workaround for one.
    """
    try:
        return (frames or _FRAMES).validate_python(payload)
    except ValidationError as exc:
        return Malformed(id=_id_of(payload), reason=str(exc))


def _id_of(payload: Any) -> str | None:
    """The correlation id of something that did not decode, if it has one.

    Worth digging for: with it the machine can answer the request that failed,
    and without it the far side is left waiting on a request nothing will ever
    answer.
    """
    if isinstance(payload, dict):
        value = payload.get("id")
        if isinstance(value, str):
            return value
    return None
