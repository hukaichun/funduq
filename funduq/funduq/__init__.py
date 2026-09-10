"""funduq's front door: the surface a serving layer holds.

`pip install funduq` used to present one name, `migrate`, and everything a
deployment actually needed was reached by knowing an internal module path in
advance. The surface was already here and simply unnamed (#280). These are
those names.

What a host holds, in the order it needs them:

- `CoreSettings` and `Funduq` — the record. Constructed with values, never
  read from the environment: configuration is an argument here.
- `AGUIAdapter`, `A2AAdapter`, `KyokAdapter` — the doors, carrier-neutral.
  They return objects, not responses; turning one into a socket is the
  serving layer's, and there is no wire in this package to reuse.
- `AgentRef`, `LlmRef` and the record types those doors speak in.
- `FunduqError` and its kinds, every one of which is a host's to turn into
  whatever its protocol says.

**Holding this surface obliges you**, and the obligations split in two: the
ones core can refuse are parameters you cannot omit, and the ones core cannot
observe are yours on your honour. Which is which is
[written down](https://github.com/hukaichun/funduq/blob/main/docs/host-obligations.md);
the honour half is the half nothing will ever tell you about.

Names resolve on first use rather than at import. `import funduq` stays what
it was — a fifth of a second, against about one when the A2A stack comes with
it — so `python -m funduq.migrate` does not pay for doors it will not open.
`funduq.migrate` is deliberately both the submodule and, after this import,
the function bound over it: `funduq.migrate()` is the documented entry, and
`python -m funduq.migrate` keeps resolving to the module.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from funduq.migrate import migrate


# name -> the module it lives in. The single place the front door is stated;
# a test walks it, so a name here that does not resolve fails loudly.
_FRONT_DOOR = {
    "Funduq": "funduq.core",
    "CoreSettings": "funduq.config",
    "AGUIAdapter": "funduq.protocols.agui",
    "EventStream": "funduq.protocols.agui",
    "ThreadSnapshot": "funduq.protocols.agui",
    "A2AAdapter": "funduq.protocols.a2a",
    "A2ARequestHandler": "funduq.protocols.a2a",
    "ServedInterface": "funduq.protocols.a2a",
    "KyokAdapter": "funduq.protocols.kyok",
    "AgentRef": "funduq.models",
    "LlmRef": "funduq.models",
    "AgentRecord": "funduq.models",
    "AgentSummary": "funduq.models",
    "LlmSummary": "funduq.models",
    "RunRecord": "funduq.models",
    "FunduqError": "funduq.errors",
    "AgentInUse": "funduq.errors",
    "AgentNotFound": "funduq.errors",
    "InvalidRegistration": "funduq.errors",
    "InvalidRunInput": "funduq.errors",
    "KyokRejected": "funduq.errors",
    "LlmOfferingInUse": "funduq.errors",
    "LlmProviderNotFound": "funduq.errors",
    "NoPendingAsk": "funduq.errors",
    "PresenterRequired": "funduq.errors",
    "RunNotCancellable": "funduq.errors",
    "RunNotFound": "funduq.errors",
    "StreamTaken": "funduq.errors",
}

__all__ = ["migrate", *sorted(_FRONT_DOOR)]


if TYPE_CHECKING:
    # For readers and type checkers only — at runtime these arrive through
    # `__getattr__`, which is what keeps the import cheap.
    from funduq.config import CoreSettings as CoreSettings
    from funduq.core import Funduq as Funduq
    from funduq.errors import (
        AgentInUse as AgentInUse,
        AgentNotFound as AgentNotFound,
        FunduqError as FunduqError,
        InvalidRegistration as InvalidRegistration,
        InvalidRunInput as InvalidRunInput,
        KyokRejected as KyokRejected,
        LlmOfferingInUse as LlmOfferingInUse,
        LlmProviderNotFound as LlmProviderNotFound,
        NoPendingAsk as NoPendingAsk,
        PresenterRequired as PresenterRequired,
        RunNotCancellable as RunNotCancellable,
        RunNotFound as RunNotFound,
        StreamTaken as StreamTaken,
    )
    from funduq.models import (
        AgentRecord as AgentRecord,
        AgentRef as AgentRef,
        AgentSummary as AgentSummary,
        LlmRef as LlmRef,
        LlmSummary as LlmSummary,
        RunRecord as RunRecord,
    )
    from funduq.protocols.a2a import (
        A2AAdapter as A2AAdapter,
        A2ARequestHandler as A2ARequestHandler,
        ServedInterface as ServedInterface,
    )
    from funduq.protocols.agui import (
        AGUIAdapter as AGUIAdapter,
        EventStream as EventStream,
        ThreadSnapshot as ThreadSnapshot,
    )
    from funduq.protocols.kyok import KyokAdapter as KyokAdapter


def __getattr__(name: str):
    module = _FRONT_DOOR.get(name)
    if module is None:
        raise AttributeError(f"module 'funduq' has no attribute '{name}'")
    return getattr(importlib.import_module(module), name)


def __dir__() -> list[str]:
    return sorted(__all__)
