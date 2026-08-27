# The link protocol machine

The link's state machine is code, in `funduq_provider_sdk.protocol`. Both
halves, sans-io: they consume frames, emit frames and events, perform no I/O
and read no clock.

[Writing a transport](writing-a-transport.md) is still the page that explains
*why* each rule exists. This one is what a transport mounts instead of
re-deriving them.

## What was actually missing

`funduq_provider_sdk/contract.py` already published a machine-readable half of
the link — `LINK_REPORT_METHODS`, `LINK_QUERY_METHODS`,
`CONNECTED_PROVIDER_ATTRS`: method names and argument orders, with not one
**state** among them. So what shipped was the half that was never expensive,
and what stayed in prose was the half that is: states, orderings, timers.

The consequence was not hypothetical. "A dropped socket ends nothing" was true
when four downstream implementations were written against it, and stopped
being true when `unregister_provider` began telling a run's lane
`ProviderGone`. No frame changed shape.

## The I/O boundary

Three seams, and the machines sit at the innermost:

```
bytes on a socket      ← the transport's, and never ours
      ↕
the wire form          ← a codec's; a default JSON one ships and is swappable
      ↕
Frame                  ← the machines' boundary
      ↕
Event                  ← the driver turns each into one Funduq call
```

Time enters as `now` and leaves as `next_deadline()`. That, not the absence of
types, is what sans-io buys — and it is what makes the orderings testable: a
race is an ordered list of `feed` calls and a clock the test sets, rather than
a sleep. `tests/test_protocol_is_io_free.py` enforces it, statically and
behaviourally.

Every method on both machines returns a `Turn` — the frames to send and the
events to act on — so a driver has one shape to handle and the order is never
in question.

**Everything crossing either boundary is a pydantic model.** This surface is a
specification for people implementing against it, and an annotation nothing
enforces specifies nothing. It also means the default codec is not a module
anyone writes: `model_dump(by_alias=True)` and `model_validate`, the same
mechanism `DeliveredRun` uses and [`contract-vectors.json`](contract-vectors.json)
pins. Frames and events differ in one setting — frames carry camelCase
aliases because they go on a wire, events carry none — not in kind.

## The frame vocabulary

| class | frames | carries `id` |
|---|---|---|
| handshake | `Connect`, `ConnectOk`, `ConnectErr` | no — there is exactly one |
| request | `Offer`, `Query`, `Register`, `Delete` | yes |
| reply | `Ok`, `Err` | yes, the request's |
| notify | `Report`, `Finish`, `Cancel` | no |

`Ok` for an offer carries the three-valued answer as an explicit discriminant
— `verdict` of `accepted`, `declined` or `refused` — and the machine converts
it to core's own `bool | Refusal` at the event boundary and nowhere else, so
neither vocabulary leaks into the other. `Err` is reserved for a request
funduq rejected, so a provider's permanent refusal and a rejection by funduq
never share a shape.

`Report.event` is `Any`: the one field the machine must not parse, because an
event whose `type` funduq does not know is relayed untouched.

A payload the codec cannot read becomes a `Malformed` — a frame like any
other, never encoded, so the decision about it stays in the transition table
and the codec never makes a protocol judgement.

!!! warning "Two dump rules that pull opposite ways"

    A **frame** is dumped `by_alias=True` and **without** `exclude_none`; a
    typed **AG-UI event** is dumped with it.

    `RunAgentInput` has required fields that are legitimately `null` —
    `state`, `forwardedProps` — so stripping nulls from a frame yields a
    `runInput` the far side cannot rebuild, and a perfectly good run comes
    back as a permanent refusal. Leaving them in an event injects
    `timestamp: null` and `rawEvent: null` into the caller's stream.

    The two rules lived in different paragraphs of `writing-a-transport.md`
    and never met until one function had to do both. The codec carried the
    flag in its first draft and a test caught it.

## FunduqSide — link states

| state | input | → | frames out | events out |
|---|---|---|---|---|
| `AWAITING_CONNECT` | `Connect` | `VERIFYING` | — | `ConnectRequested` |
| `AWAITING_CONNECT` | any other frame | `CLOSED` | `ConnectErr` | `LinkFailed` |
| `VERIFYING` | `accept_connect(answer)` | `OPEN` | `ConnectOk(answer)` | — |
| `VERIFYING` | `refuse_connect(reason)` | `CLOSED` | `ConnectErr(reason)` | — |
| `VERIFYING` | any frame | `CLOSED` | `ConnectErr` | `LinkFailed` |
| `OPEN` | `Connect` | `CLOSED` | `Err` | `LinkFailed` |
| `OPEN` | `Register(id, agents)` | `OPEN` | — | `Registering` |
| `OPEN` | `Delete(id, name)` | `OPEN` | — | `Deleting` |
| `OPEN` | `Query(id, method, args)` | `OPEN` | — | `Asking` |
| `OPEN` | `Report(run_id, event)` | `OPEN` | — | `Reported` |
| `OPEN` | `Finish(run_id)` | `OPEN` | — | `Finished` |
| `OPEN` | `Ok(id, verdict)` | `OPEN` | — | see the offer table |
| `OPEN` | `Malformed(id, reason)` | `OPEN` | `Err(id, reason)` | — |
| `OPEN` | `offer(run, now)` *from core* | `OPEN` | `Offer(id, run)` | — |
| `OPEN` | `cancel(run_id)` *from core* | `OPEN` | `Cancel(run_id)` | — |
| any | `connection_lost()` | `CLOSED` | — | `Gone(unanswered, dropped)` |

Two rows are absent on purpose, and their absence is the design:

**There is no registration state.** The machine never learns which agents the
link serves, so an offer arriving before a `Register` has been answered
violates nothing. The window is real and wide: `_Roster.register` puts the
roster live and nudges the broker at `core.py:267`, then does a `touch` and a
`commit` — a network round trip on Postgres — before `register_agents`
returns. A machine that refused to offer until it had answered a `Register`
would deadlock against its own broker.

**There is no ticket frame.** "Do not fetch it over the link" is no longer a
warning; it is something the vocabulary cannot say.

## FunduqSide — one offer's states

Keyed by the request `id`, armed with a deadline of `now + deliver_timeout`
(core's own `deliver_timeout_seconds`, handed in rather than defaulted, so one
number has one definition).

| state | input | → | events out |
|---|---|---|---|
| — | `offer(run)` from core | `OFFERED` | — (deadline armed) |
| `OFFERED` | `Ok(accepted)` | `CLAIMED` | `Answered(id, True)` |
| `OFFERED` | `Ok(declined)` | `DECLINED` | `Answered(id, False)` |
| `OFFERED` | `Ok(refused, reason)` | `REFUSED` | `Answered(id, Refusal(reason))` |
| `OFFERED` | deadline reached | `UNANSWERED` | `Unanswered(id)` |
| `UNANSWERED` | `Ok(…)` | `UNANSWERED` | `Answered(id, …, late=True)` |
| settled | `Ok(…)` | `CLOSED` | `LinkFailed("answered twice")` |

A timed-out offer keeps its id. Forgetting it is the instinct, and it turns a
provider's late honesty into a protocol error.

## ProviderSide

| state | input | → | frames out | events out |
|---|---|---|---|---|
| `IDLE` | `connect(ticket, …)` | `CONNECTING` | `Connect` | — |
| `CONNECTING` | `ConnectOk`, signature verifies | `OPEN` | — | `Opened` |
| `CONNECTING` | `ConnectOk`, signature does not | `CLOSED` | — | `LinkFailed` |
| `CONNECTING` | `ConnectErr(reason)` | `CLOSED` | — | `Refused(reason)` |
| `CONNECTING` | any other frame | `CLOSED` | — | `LinkFailed` |
| `OPEN` | `Offer(id, run)` | `OPEN` | — | `Offered(id, run)` |
| `OPEN` | `Malformed(id, reason)` | `OPEN` | `Ok(id, refused, reason)` | — |
| `OPEN` | `Cancel(run_id)` | `OPEN` | — | `Cancelled` |
| `OPEN` | `Ok(id, payload)` / `Err(id, reason)` | `OPEN` | — | `Replied` / `Failed` |
| `OPEN` | `answer(id, verdict)` *from runtime* | `OPEN` | `Ok(id, verdict)` | — |
| `OPEN` | `report` / `finish` | `OPEN` | `Report` / `Finish` | — |
| `OPEN` | `register` / `delete` / `ask` | `OPEN` | the request frame | — |

The machine **signs** the connect rather than taking a proof, because the one
thing a transport author must not get wrong there is *what* is signed: the
pinned funduq key goes into the bytes, so a proof one funduq coaxes out cannot
be relayed to attach at another. And "check the answer before producing
anything" is structural — `CONNECTING` emits no other frame.

A run that will not decode never becomes an `Offer`: the codec yields
`Malformed` and the row above answers it as a permanent refusal, so the agent
never hears about it.

## What the machines do not do

1. **They do not gate `Report` or `Finish` on the offer table.** Those are
   addressed by run, and whether a key may speak for a run is core's question,
   answered against `claimed_by` — which includes letting a provider claim
   late by producing for a run funduq had given up waiting for. Gating them
   here looks obviously right and would make that path unreachable over a wire
   while leaving it working in-process.
2. **They do not decide a run's outcome on `connection_lost`.** The machine
   reports `Gone`; core holds the verdict. funduq never decides on a
   provider's behalf.
3. **They do not hold or mint a ticket.**
4. **They do not filter unknown AG-UI event types.**
5. **They do not reorder.** One link, frames in arrival order.

## Two things building it found

**`maxConcurrentRuns` had nowhere to travel.** Core schedules against
`ConnectedProvider.max_concurrent_runs`; in-process reads it off the runtime;
the frame vocabulary had no field for it. It is on `Connect` now — declared at
the open, because it is a property of the party on the other end and not of
any agent it publishes. Drawing the tables did not surface this. Wiring a
driver to a real broker did, immediately.

**Core's late-claim path is unreachable from a late answer.**
`accept_late_ack` is called from `report_event`, when a provider begins
producing for a run funduq gave up waiting for; nothing accepts a late `Ok`.
So `UNANSWERED → Answered(late=True)` has no core call behind it and the
driver can only log it. Recorded rather than designed around: either the row
is honest about being evidence only, or `accept_late_ack` grows an ack-shaped
entry point.

## Conformance

`funduq/tests/test_protocol_loopback.py` wires the two machines to each other
**through the codec**, with a real `Funduq` at one end and a real
`ProviderRuntime` at the other. No socket, no sleep. It lives in core's suite
because the SDK may not import core — and because a machine only downstream
exercises would rot the way the prose did.

The drivers in that file are the part a transport author writes, and they are
short on purpose: pump frames, and turn each event into the one `Funduq` call
it names. Everything else is in the machines.

## Adoption without a flag day

The machines work in `Frame` models; the codec is a separate seam. A transport
that already has a wire substitutes its own codec and still takes the state
handling. `FunduqLink` is unchanged and still supported — it remains the right
surface for *provider authors*, who should never meet a frame, and stops being
what *transport authors* subclass.

Core changed nothing: `FunduqSide` calls only `attach_provider`,
`register_agents`, `delete_agent`, `report_event`, `finish_run`,
`get_thread_messages` and `detach_provider`, and core does not import the SDK.

## What is not built yet

- **The LLM link.** `FunduqLLMLink`'s shape is a stream of chunks rather than
  one answer, so it needs its own event family.
- **Resume** ([#214](https://github.com/hukaichun/funduq/issues/214)). The
  machines are already instantiated per session rather than per connection,
  which is what resume needs: a drop is `connection_lost()`, a reconnect
  installs a new send callback, and per-run sequence and delivery watermark
  can survive both. That state could never have lived in a `FunduqLink`
  instance, because that instance is what is thrown away on every blip — which
  is why #214 is not a grace-window keyword argument. The machine would own
  the resume mechanics; core would own the verdict. Note that
  `ProviderRuntime._report_output` still drops events emitted while no link is
  attached, so the runtime has to buffer before any of this is reachable.
