# Proposed: the link protocol as a machine

!!! warning "Nothing on this page is built"

    This is a design for [#213](https://github.com/hukaichun/funduq/issues/213),
    written in the future tense on purpose. No identifier here exists yet.
    When it does, this page is replaced by a tour of the shipped code and
    [Writing a transport](writing-a-transport.md) is demoted to the same.

## What is actually missing

`funduq_provider_sdk/contract.py` already publishes a machine-readable half
of the link:

```python
LINK_REPORT_METHODS = {"report_event": ("run_id", "event"), "finish_run": ("run_id",)}
LINK_QUERY_METHODS  = {"thread_messages": ("thread_id", "limit")}
CONNECTED_PROVIDER_ATTRS = frozenset({"public_key", "max_concurrent_runs", "deliver", "cancel"})
```

Method names and argument orders. What it does not contain is a single
**state**. Every ordering rule lives in [Writing a
transport](writing-a-transport.md) as English — so what upstream ships is the
half that was never expensive, and what it keeps in prose is the half that is:
states, orderings, timers.

The consequence is not hypothetical. "A dropped socket ends nothing" was true
when four downstream implementations were written against it, and is not true
now: `unregister_provider` tells the run's lane `ProviderGone` and a claimed
run fails as `provider_left_holding_it`. No frame changed shape.

## The I/O boundary

Three seams, and the machine sits at the innermost one:

```
bytes on a socket      ← the transport's, and never ours
      ↕
the wire form          ← a codec's; a default JSON one ships and is swappable
      ↕
Frame                  ← the machine's boundary
      ↕
Event                  ← the driver turns each into one Funduq call
```

The machine performs no I/O and reads no clock: time enters as `now` and
leaves as `next_deadline()`. That, not the absence of types, is what sans-io
buys — and it is what makes the tables below testable, because a race becomes
an ordered list of `feed` calls and a clock the test sets rather than a sleep.

```python
machine.feed(frame: Frame, *, now: float) -> list[Event]
send_frame(frame: Frame)
```

**Everything crossing either boundary is a pydantic model.** This surface is a
specification for people implementing against it, and an annotation nothing
enforces specifies nothing — which is the disease this whole issue is about,
one document further up. Models also mean the default codec is not a module
anyone writes: it is `model_dump(by_alias=True)` and `model_validate`, the
same mechanism `DeliveredRun` already uses and
[`contract-vectors.json`](contract-vectors.json) already pins, so a vector
entry validates straight into a frame.

Frames and events differ in one setting, not in kind: **frames carry
camelCase aliases because they go on a wire, events carry none because they do
not.**

## The frame vocabulary

Four classes, and the class decides the correlation rule.

| class | frames | carries `id` |
|---|---|---|
| handshake | `Connect`, `ConnectOk`, `ConnectErr` | no — there is exactly one |
| request | `Offer`, `Query`, `Register`, `Delete` | yes |
| reply | `Ok`, `Err` | yes, the request's |
| notify | `Report`, `Finish`, `Cancel` | no |

Every one is a `BaseModel` with camelCase aliases, nesting the models that
already exist:

```python
class Offer(Frame):
    model_config = ConfigDict(frozen=True, populate_by_name=True)
    id: str
    run: DeliveredRun            # the published delivered-run envelope, unchanged

class Ok(Frame):
    id: str
    verdict: Literal["accepted", "declined", "refused"] | None = None
    reason: str | None = None
    payload: Any = None
```

The three-valued answer carries an explicit discriminant **on the wire**, and
the machine converts it to core's own `bool | Refusal` at the event boundary.
Neither vocabulary leaks into the other: the wire never relies on a union
being told apart by inspection, and core keeps the two types it already reads.

`Err` is reserved for a request funduq rejected, so a provider's permanent
refusal and a rejection by funduq never share a shape.

`Report.event` stays `Any` — the one field that must not be parsed, because an
event whose `type` funduq does not know is relayed untouched. The dump that
produces it is the machine's, with `exclude_none=True`, which turns a rule
every transport currently has to remember into one none of them can get
wrong: a default dump injects `timestamp: null` and `rawEvent: null` into the
caller's stream.

A frame the codec cannot parse becomes a `Malformed(id, reason)` — a frame
like any other, so the decision about it stays in the transition table and the
codec never makes a protocol judgement.

## Two machines

`FunduqSide` is what a gateway mounts between its socket and a `Funduq`
object; it presents exactly `CONNECTED_PROVIDER_ATTRS` to core.
`ProviderSide` is its mirror. Neither imports asyncio.

Events are models too, without aliases — `Answered`, `Reported`, `Offered`,
`Gone`. The driver's whole job is to turn each into the one `Funduq` call it
names.

### FunduqSide — link states

| state | input | → | frames out | events out |
|---|---|---|---|---|
| `AWAITING_CONNECT` | `Connect` | `VERIFYING` | — | `ConnectRequested(key, ticket, nonce, proof)` |
| `AWAITING_CONNECT` | any other frame | `CLOSED` | `ConnectErr` | `LinkFailed("first frame must be Connect")` |
| `VERIFYING` | `accept_connect(answer)` | `OPEN` | `ConnectOk(answer)` | — |
| `VERIFYING` | `refuse_connect(reason)` | `CLOSED` | `ConnectErr(reason)` | — |
| `VERIFYING` | any frame | `CLOSED` | `ConnectErr` | `LinkFailed("spoke while connect was being verified")` |
| `OPEN` | `Connect` | `CLOSED` | `Err` | `LinkFailed("already open")` |
| `OPEN` | `Register(id, agents)` | `OPEN` | — | `Registering(id, agents)` |
| `OPEN` | `Delete(id, name)` | `OPEN` | — | `Deleting(id, name)` |
| `OPEN` | `Query(id, method, args)` | `OPEN` | — | `Asking(id, method, args)` |
| `OPEN` | `Report(run_id, event)` | `OPEN` | — | `Reported(run_id, event)` |
| `OPEN` | `Finish(run_id)` | `OPEN` | — | `Finished(run_id)` |
| `OPEN` | `Ok(id, verdict)` | `OPEN` | — | see the offer table |
| `OPEN` | `Malformed(id, reason)` | `OPEN` | `Err(id, reason)` | — |
| `OPEN` | `offer(run, now)` *from core* | `OPEN` | `Offer(id, run)` | — |
| `OPEN` | `cancel(run_id)` *from core* | `OPEN` | `Cancel(run_id)` | — |
| `OPEN` | `reply_ok/err(id, …)` *from driver* | `OPEN` | `Ok`/`Err(id, …)` | — |
| any | `connection_lost(now)` | `CLOSED` | — | `Gone(unanswered_offers, dropped_queries)` |

Two rows are absent on purpose, and their absence is the design:

**There is no registration state.** The link machine never learns which agents
are served, so an offer arriving before a `Register` has been replied to is
not an allowance — there is nothing for it to violate. That matters because
the window is real and wide: `_Roster.register` puts the roster live and
nudges the broker at `core.py:267`, then does a `touch` and a `commit` — a
network round trip on Postgres — before `register_agents` returns.

**There is no ticket frame.** "Do not fetch the ticket over the link" stops
being a warning and becomes something the vocabulary cannot express.

### FunduqSide — one offer's states

Keyed by the request `id`, armed with a deadline of `now + deliver_timeout`.

| state | input | → | events out |
|---|---|---|---|
| — | `offer(run)` from core | `OFFERED` | — (deadline armed) |
| `OFFERED` | `Ok(accepted)` | `CLAIMED` | `Answered(id, True)` |
| `OFFERED` | `Ok(declined)` | `DECLINED` | `Answered(id, False)` |
| `OFFERED` | `Ok(refused, reason)` | `REFUSED` | `Answered(id, Refusal(reason))` |
| `OFFERED` | deadline reached | `UNANSWERED` | `Unanswered(id)` |
| `UNANSWERED` | `Ok(…)` | `UNANSWERED` | `Answered(id, …, late=True)` |
| `CLAIMED`/`DECLINED`/`REFUSED` | `Ok(…)` | `CLOSED` | `LinkFailed("second answer for offer <id>")` |

The wire's `Literal["accepted","declined","refused"]` becomes core's
`bool | Refusal` here and nowhere else, which is the whole of the conversion.

`next_deadline()` is the minimum armed deadline; `timeout(now)` fires the ones
that have passed. The only clock on this side.

### ProviderSide

| state | input | → | frames out | events out |
|---|---|---|---|---|
| `IDLE` | `connect(ticket, nonce, proof)` | `CONNECTING` | `Connect(…)` | — |
| `CONNECTING` | `ConnectOk`, signature verifies | `OPEN` | — | `Opened()` |
| `CONNECTING` | `ConnectOk`, signature does not | `CLOSED` | — | `LinkFailed(WrongFunduq)` |
| `CONNECTING` | `ConnectErr(reason)` | `CLOSED` | — | `Refused(reason)` |
| `CONNECTING` | any other frame | `CLOSED` | — | `LinkFailed("spoke before the answer")` |
| `OPEN` | `Offer(id, run)` | `OPEN` | — | `Offered(id, run)` |
| `OPEN` | `Malformed(id, reason)` | `OPEN` | `Ok(id, refused, reason)` | — |
| `OPEN` | `Cancel(run_id)` | `OPEN` | — | `Cancelled(run_id)` |
| `OPEN` | `Ok(id, payload)` | `OPEN` | — | `Replied(id, payload)` |
| `OPEN` | `Err(id, reason)` | `OPEN` | — | `Failed(id, reason)` |
| `OPEN` | `answer(id, verdict)` *from runtime* | `OPEN` | `Ok(id, verdict)` | — |
| `OPEN` | `report(run_id, event)` | `OPEN` | `Report(…)` | — |
| `OPEN` | `finish(run_id)` | `OPEN` | `Finish(…)` | — |
| `OPEN` | `register(agents)` / `ask(method, args)` | `OPEN` | `Register`/`Query(id, …)` | — |

A run that does not validate as `RunAgentInput` never becomes an `Offer` at
all: the codec yields `Malformed`, and the row above answers it as a permanent
refusal. That is where `FunduqLink.deliver` does it today, and it is a rule
about the frame rather than about the provider, so every transport should get
it without writing it.

Verifying `ConnectOk` is likewise the machine's, using `funduq_contract`'s
pure `verify_signature` and `funduq_connect_payload` — and "check before
producing anything" becomes structural, because `CONNECTING` emits no other
frame.

## What the machine must not do

1. **Not gate `event` or `finish` on its own offer table.** They are addressed
   by `runId`, and authorization is core's, keyed on `claimed_by`. Gating them
   locally looks obviously right and breaks late-claim (below).
2. **Not decide a run's outcome on `connection_lost`.** It reports `Gone`;
   core holds the verdict. funduq never decides on a provider's behalf.
3. **Not hold or mint a ticket.**
4. **Not filter unknown AG-UI event types.** Three-way validation is core's,
   and a relay that filters is not a relay.
5. **Not reorder.** One link, frames in arrival order.

## A gap this design found

Core's late-claim path is not reachable from a late answer. `accept_late_ack`
is called from `report_event`, when the provider begins *producing* for a run
whose ack funduq gave up on — there is no path that accepts a late `ok`. So
the `UNANSWERED → Answered(late=True)` row above has no core call behind it;
the driver can only log it.

That is a finding, not a thing to design around: either the row is honest
about being evidence-only, or `accept_late_ack` grows an ack-shaped entry
point. Writing the table is what surfaced it — the prose had described this
area for two transport generations without it showing.

## Conformance

`FunduqSide` and `ProviderSide` wired to each other through the codec — so
every frame makes the `model_dump` / `model_validate` round trip the wire
would make — with a real `Funduq` at one end and a real `ProviderRuntime` at
the other. No socket, no sleep, clock supplied as data. Every row above becomes an ordered script,
including the ones no test can reach today: an answer on a second
fully-credentialed connection, an answer after the timeout, an offer before a
registration is replied to, a second `Connect` on an open link.

The loopback lives in this repository's suite. A machine only downstream
exercises would rot exactly the way the prose did.

## Adoption without a flag day

The machines work in `Frame` models; the default codec is
`model_dump(by_alias=True)` and `model_validate`, and it is the codec's output
that gains `contract-vectors.json` entries. A transport that already has a
wire substitutes its own codec and still takes the state handling — which is
what makes the seam real, rather than the machine's interface quietly *being*
the JSON codec's output. The complaint in #213 is being forced into flag days,
and answering it with one more would answer it badly.

Note that the vectors cannot carry any invariant on this page — they pin frame
shapes, and every rule here is an ordering. The conformance suite is new
machinery, not a replay of the vectors.

## Core changes: none

`FunduqSide` calls only `attach_provider`, `register_agents`, `delete_agent`,
`report_event`, `finish_run`, `thread_messages` and `detach_provider`. Core
does not import the SDK today and will not after this.

## Where it lives

`funduq_provider_sdk.protocol`, both halves, not a new distribution: the
package already owns `DeliveredRun`, the ABC and the field sets; the
funduq-side half imports nothing from core, only the duck-typed shapes core
already reads; and revisions 5–7 landing in one day is evidence that
versioning another distribution is a real cost. The name being
provider-flavoured on both halves is cosmetic.

`FunduqLink` stays — it is the right surface for *provider authors*, who
should never meet a frame — and stops being what *transport authors*
subclass. A transport instantiates `ProviderSide` and hands it two callbacks.

Two consequences for the package's neighbours, named rather than tidied away.
`pydantic` arrives today only through `ag-ui-protocol`; once the protocol
surface is models it is a direct dependency and belongs in the list. And
`Refusal` next door stays a frozen dataclass — core duck-types its `.reason`,
so changing it carries a compatibility bill for no gain here, and the
inconsistency is real. `AgentHandle.as_registration()`, which hand-writes a
dict today, is the kind of mapping a `Register` model removes.

## Order of work

1. Frames, `FunduqSide`, `ProviderSide`, and the loopback. Behaviour identical
   to today, so it is a refactor with a harness rather than a feature.
2. This page becomes a tour of the shipped code; `writing-a-transport.md`
   likewise. `test_core_is_network_free`'s guard extends over `protocol/`, so
   the sans-io claim is enforced rather than asserted.
3. The LLM link, whose shape is a stream of chunks rather than one answer and
   so needs its own event family.
4. Resume ([#214](https://github.com/hukaichun/funduq/issues/214)) — last, and
   this design exists partly to make it reachable. The machines are
   instantiated **per session, not per connection**: a drop is
   `connection_lost()`, a reconnect installs a new `send_frame`, and per-run
   sequence and delivery watermark survive both. That state cannot live in a
   `FunduqLink` instance, because that instance is what is thrown away on
   every blip — which is why #214 is not a grace-window keyword argument.

   The split: the machine owns resume mechanics; core owns the verdict (how
   long before `provider_left_holding_it`, and whether a resumed run still
   counts `abandoned`). `ProviderRuntime._report_output` currently drops
   events emitted while no link is attached, so resume is unreachable until
   the runtime buffers — more reason it follows the protocol work rather than
   leading it.
