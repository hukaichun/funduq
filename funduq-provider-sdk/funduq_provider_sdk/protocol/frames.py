from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from funduq_provider_sdk.provider import DeliveredRun, Registration


class Frame(BaseModel):
    """One thing that crosses the link, as a model rather than a dict.

    The wire form is `model_dump(mode="json", by_alias=True, exclude_none=True)`
    and `model_validate` rebuilds it — the same mechanism `DeliveredRun` uses
    and `docs/contract-vectors.json` pins, so the camelCase mapping is written
    once here instead of once per transport. A field annotation nothing
    enforces specifies nothing, and this surface exists to specify.

    `kind` is the discriminator; `codec.decode` reads it and nothing else has
    to.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)


class Connect(Frame):
    """Opens the link, carrying the proof funduq's ticket asked for.

    There is deliberately no frame that *obtains* a ticket. "Do not fetch it
    over the link being opened" stops being a warning a transport author has
    to read and becomes something the vocabulary cannot say."""

    kind: Literal["connect"] = "connect"
    public_key: str = Field(alias="publicKey")
    ticket: str
    nonce: str
    proof: str
    max_concurrent_runs: int | None = Field(default=None, alias="maxConcurrentRuns")
    """How many runs this link will hold at once, `None` for no limit.

    Declared at the open rather than with a registration, because it is a
    property of the party on the other end of this connection and not of any
    agent it publishes. funduq takes the figure at its word — a decline from a
    provider that claimed no limit is counted as abnormal — so it belongs
    where the party is proved."""


class ConnectOk(Frame):
    """funduq's answering signature over both nonces, or `None` from a funduq
    with no identity — which only a provider that pinned a key treats as a
    failure."""

    kind: Literal["connect.ok"] = "connect.ok"
    answer: str | None = None


class ConnectErr(Frame):

    kind: Literal["connect.err"] = "connect.err"
    reason: str


class Offer(Frame):
    """A run handed down for an answer. `run` is the published delivered-run
    envelope, nested rather than restated."""

    kind: Literal["offer"] = "offer"
    id: str
    run: DeliveredRun


class ThreadMessages(Frame):
    """Ask funduq for a thread's history.

    Its own frame rather than a `method` string and a bag of `args`. That
    shape was published once already — `LINK_QUERY_METHODS` names the method
    and its argument order, and nothing checks either — and it is the pattern
    this package exists to stop: a transport ends up writing
    `args["thread_id"]` by hand, which is how a field name goes wrong
    silently. A second query kind is a second frame, and adding one moves the
    contract fingerprint, which is the right price."""

    kind: Literal["query.thread_messages"] = "query.thread_messages"
    id: str
    thread_id: str = Field(alias="threadId")
    limit: int | None = None


class Register(Frame):
    """Publish this link's agents.

    `agents` is a list of `Registration`, not of loose dicts: the shape was
    already published without a type, so a misspelt key travelled intact and
    core dropped it silently."""

    kind: Literal["register"] = "register"
    id: str
    agents: list[Registration]


class Delete(Frame):

    kind: Literal["delete"] = "delete"
    id: str
    name: str


class Ok(Frame):
    """The answer to a request, and — for an offer — the three-valued one.

    `verdict` carries an explicit discriminant on the wire instead of a union
    told apart by inspection; the machine converts it to core's own
    `bool | Refusal` at the event boundary and nowhere else, so neither
    vocabulary leaks into the other. A transport that collapses the three
    values into one bit re-creates a bug funduq already had: runs re-offered
    forever, reading `queued` from every vantage point while only the
    provider's log knew."""

    kind: Literal["ok"] = "ok"
    id: str
    verdict: Literal["accepted", "declined", "refused"] | None = None
    reason: str | None = None
    payload: Any = None


class Err(Frame):
    """A request the far side rejected — never a provider's permanent refusal
    of a run, which is `Ok(verdict="refused")`. The two must not share a
    shape: one says the work will never be done, the other says the request
    was wrong."""

    kind: Literal["err"] = "err"
    id: str
    reason: str


class Report(Frame):
    """One event, relayed.

    `event` is `Any` on purpose — the single field the machine must not parse.
    An event carrying a `type` funduq does not know is relayed untouched, so a
    provider on a newer AG-UI is not cut off by a vocabulary funduq has not
    heard of. The dump that fills this field is the machine's, with
    `exclude_none=True`, because a default dump injects `timestamp: null` and
    `rawEvent: null` into the caller's stream."""

    kind: Literal["report"] = "report"
    run_id: str = Field(alias="runId")
    event: Any = None


class Finish(Frame):

    kind: Literal["finish"] = "finish"
    run_id: str = Field(alias="runId")


class Cancel(Frame):
    """funduq asking a provider to stop. It is a request to the agent, not a
    verdict on the run: funduq never decides an outcome on a provider's
    behalf, so nothing here settles anything."""

    kind: Literal["cancel"] = "cancel"
    run_id: str = Field(alias="runId")


class Malformed(Frame):
    """Something arrived that the codec could not turn into a frame.

    Not a wire frame — it is never encoded, and it is not in `WireFrame`. It
    exists so a decode failure enters the machine as an ordinary input and the
    transition table decides what happens to it. A codec that answered on its
    own would be making protocol judgements from outside the machine, which is
    the split this package exists to close."""

    kind: Literal["malformed"] = "malformed"
    reason: str
    id: str | None = None


WireFrame = Annotated[
    Union[
        Connect,
        ConnectOk,
        ConnectErr,
        Offer,
        ThreadMessages,
        Register,
        Delete,
        Ok,
        Err,
        Report,
        Finish,
        Cancel,
    ],
    Field(discriminator="kind"),
]
