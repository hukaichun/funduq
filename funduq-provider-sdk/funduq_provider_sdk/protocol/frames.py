from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from funduq_provider_sdk.provider import DeliveredRun, Registration


class Frame(BaseModel):
    """One thing that crosses the link, as a model rather than a dict."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)


class Connect(Frame):
    """Opens the link, carrying the proof funduq's ticket asked for."""

    kind: Literal["connect"] = "connect"
    public_key: str = Field(alias="publicKey")
    ticket: str
    nonce: str
    proof: str
    max_concurrent_runs: int | None = Field(default=None, alias="maxConcurrentRuns")
    """How many runs this link will hold at once, `None` for no limit."""


class ConnectOk(Frame):
    """funduq's answering signature over both nonces, or `None` from a funduq with no identity — which only a provider that pinned a key treats as a failure."""

    kind: Literal["connect.ok"] = "connect.ok"
    answer: str | None = None


class ConnectErr(Frame):

    kind: Literal["connect.err"] = "connect.err"
    reason: str


class Offer(Frame):
    """A run handed down for an answer."""

    kind: Literal["offer"] = "offer"
    id: str
    run: DeliveredRun


class ThreadMessages(Frame):
    """Ask funduq for a thread's history."""

    kind: Literal["query.thread_messages"] = "query.thread_messages"
    id: str
    thread_id: str = Field(alias="threadId")
    limit: int | None = None


class Register(Frame):
    """Publish this link's agents."""

    kind: Literal["register"] = "register"
    id: str
    agents: list[Registration]


class Delete(Frame):

    kind: Literal["delete"] = "delete"
    id: str
    name: str


class Ok(Frame):
    """The answer to a request, and — for an offer — the three-valued one."""

    kind: Literal["ok"] = "ok"
    id: str
    verdict: Literal["accepted", "declined", "refused"] | None = None
    reason: str | None = None
    payload: Any = None


class Err(Frame):
    """A request the far side rejected — never a provider's permanent refusal of a run, which is `Ok(verdict="refused")`."""

    kind: Literal["err"] = "err"
    id: str
    reason: str


class Report(Frame):
    """One event, relayed."""

    kind: Literal["report"] = "report"
    run_id: str = Field(alias="runId")
    event: Any = None


class Finish(Frame):

    kind: Literal["finish"] = "finish"
    run_id: str = Field(alias="runId")


class Cancel(Frame):
    """funduq asking a provider to stop."""

    kind: Literal["cancel"] = "cancel"
    run_id: str = Field(alias="runId")


class Malformed(Frame):
    """Something arrived that the codec could not turn into a frame."""

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
