"""The link's state machine, shipped as code instead of described in prose.

Both halves, sans-io: they consume frames, emit frames and events, perform no
I/O and read no clock. What used to be a page of orderings each transport
re-derived — the handshake sequence, the three-valued answer, what a dropped
link ends — is a transition table here, and a test can drive it as an ordered
script rather than a sleep.

See `docs/link-protocol-machine.md`.
"""

from funduq_provider_sdk.protocol.codec import decode, encode
from funduq_provider_sdk.protocol.events import (
    Answered,
    AskingThreadMessages,
    Cancelled,
    ConnectRequested,
    Deleting,
    Event,
    Failed,
    Finished,
    Gone,
    LinkFailed,
    Offered,
    Opened,
    Refused,
    Registering,
    Replied,
    Reported,
    Unanswered,
)
from funduq_provider_sdk.protocol.frames import (
    Cancel,
    Connect,
    ConnectErr,
    ConnectOk,
    Delete,
    Err,
    Finish,
    Frame,
    Malformed,
    Offer,
    Ok,
    ThreadMessages,
    Register,
    Report,
    WireFrame,
)
from funduq_provider_sdk.protocol.funduq_side import FunduqSide
from funduq_provider_sdk.protocol.provider_side import ProviderSide
from funduq_provider_sdk.protocol.turn import Turn

__all__ = [
    "Answered",
    "AskingThreadMessages",
    "Cancel",
    "Cancelled",
    "Connect",
    "ConnectErr",
    "ConnectOk",
    "ConnectRequested",
    "Delete",
    "Deleting",
    "Err",
    "Event",
    "Failed",
    "Finish",
    "Finished",
    "Frame",
    "FunduqSide",
    "Gone",
    "LinkFailed",
    "Malformed",
    "Offer",
    "Offered",
    "Ok",
    "Opened",
    "ProviderSide",
    "ThreadMessages",
    "Refused",
    "Register",
    "Registering",
    "Replied",
    "Report",
    "Reported",
    "Turn",
    "Unanswered",
    "WireFrame",
    "decode",
    "encode",
]
