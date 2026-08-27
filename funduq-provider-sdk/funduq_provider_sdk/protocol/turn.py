from __future__ import annotations

from typing import NamedTuple

from funduq_provider_sdk.protocol.events import Event
from funduq_provider_sdk.protocol.frames import Frame


class Turn(NamedTuple):
    """What one input did: frames to send, and events for the driver to act on.

    Every method on both machines returns one of these, so a driver has a
    single shape to handle and the order is never in question — send the
    frames, then act on the events. An interface where some inputs answered
    with frames and others with events would leave "who replies to a frame the
    codec could not read" to be decided at each call site, which is the kind of
    thing this package exists to stop being decided four times.
    """

    frames: list[Frame] = []
    events: list[Event] = []


EMPTY = Turn([], [])
