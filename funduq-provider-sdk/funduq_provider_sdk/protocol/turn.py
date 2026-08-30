from __future__ import annotations

from typing import NamedTuple

from funduq_provider_sdk.protocol.events import Event
from funduq_provider_sdk.protocol.frames import Frame


class Turn(NamedTuple):
    """What one input did: frames to send, and events for the driver to act on."""

    frames: list[Frame] = []
    events: list[Event] = []


EMPTY = Turn([], [])
