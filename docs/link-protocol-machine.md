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

## The completion half

An LLM link opens the same way — `FunduqLinkMachine` and
`ProviderLinkMachine` carry the handshake, deleting and querying for both
kinds, so a fix to the ceremony cannot land in one copy and not the other.
What differs is the work. Both kinds are answered with a **stream** — a run's
answer is its events and then its finish — so that is not the difference. Two
things are:

**A run is admitted first.** An offer is answered three ways before any output
exists, and funduq holds the next utterance of that conversation until the run
is *claimed* — a decline answers promptly and holds it anyway, since the run
goes back to the head of its thread's queue. A completion has no admission step: it is assumed taken and can
only fail afterwards. So `FunduqLlmSide` and `ProviderLlmSide` have no
three-valued ack, and no delivery deadline to go with one. `next_deadline()`
is always `None`, deliberately: the clock that used to sit there was removed
for blaming a slow model for its own slowness, and liveness is a fact funduq
holds — whether the link is still here — not a deduction from how long a chunk
took.

**A run outlives any one offer of it; a completion does not.** A run declined
once is offered again under a new id, and a provider may claim one late by
producing for it — so its output is addressed by `runId`, and the machine
deliberately does not gate it. A completion is asked for exactly once, so its
chunks are addressed by the request's own id, and gating those on the table is
correct. The two halves differ here for a reason rather than by accident.

| frame | direction | meaning |
|---|---|---|
| `register.llm` | provider → funduq | names plus one metadata document |
| `complete` | funduq → provider | one request, carrying the delivered-completion envelope |
| `chunk` | provider → funduq | one piece of the answer, never parsed |
| `completion.end` | provider → funduq | it finished |
| `completion.failed` | provider → funduq | it did not; `refusal` present is the provider's policy |
| `abandon` | funduq → provider | the caller stopped consuming |

A completion is `OPEN` until exactly one of `completion.end`,
`completion.failed` or a lost link. A chunk after the end breaks the link, and
so does ending a completion that was never asked for.

They live under `llm/` because they name `DeliveredCompletion`, which reaches
openai's types — an agent provider must not pay that import, which is why the
completion half is an extra. Each link kind has its own codec, which is the
shape of the thing rather than a workaround: an agent link and an LLM link are
different connections to different rosters.

## Four things building it found

**`maxConcurrentRuns` had nowhere to travel.**

**`maxConcurrentRuns` had nowhere to travel.** Core schedules against
`ConnectedProvider.max_concurrent_runs`; in-process reads it off the runtime;
the frame vocabulary had no field for it. It is on `Connect` now — declared at
the open, because it is a property of the party on the other end and not of
any agent it publishes. Drawing the tables did not surface this. Wiring a
driver to a real broker did, immediately.

**The two links do not publish their rosters the same way.** They looked like
one `register` frame until the LLM roster's `metadata` had nowhere to travel:
agents are published as records, offerings as names plus one document
describing the link's terms. Registration moved out of the shared base and
into each work family. Sharing the frame would have meant dropping the
metadata or carrying a field that is always empty on one side.

**A caller that stops consuming had no way to say so.** In-process that is
`GeneratorExit` arriving in the handler; over a wire nothing reached the
provider at all, so it went on generating into a consumer that had gone. The
`abandon` frame is the wire's version, and it needs no new core verb —
`ConnectedLLMProvider` has none to add, and a driver knows when its own stream
was closed.

**Core's late-claim path is unreachable from a late answer.**
`accept_late_ack` is called from `report_event`, when a provider begins
producing for a run funduq gave up waiting for; nothing accepts a late `Ok`.
So `UNANSWERED → Answered(late=True)` has no core call behind it and the
driver can only log it. Recorded rather than designed around: either the row
is honest about being evidence only, or `accept_late_ack` grows an ack-shaped
entry point.

## Conformance

`funduq/tests/test_protocol_loopback.py` and
`test_protocol_llm_loopback.py` wire each pair of machines to each other
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

## Resume: a blip stops ending a run

A provider behind NAT on a consumer connection is the party outbound dispatch
exists for, and for that party a two-second drop is weather. It used to cost
the caller its run and the provider an `abandoned` mark for work it was still
doing. Three things had to move together, which is why this was never a
keyword argument.

**Core stopped welding two facts together.** A link going away and a provider
giving up were one act: `unregister_provider` withdrew the roster *and* told
every run its provider was gone. Now the roster still loses the key at once —
nothing new is handed to somebody who is not there — while what it holds waits
out `CoreSettings.provider_grace_seconds`. `expire_gone_providers` is the
clock, and it sits beside `expire_queued` for a reason: both are clocks over
something funduq observed, rather than deductions about how a provider is
doing. **The default is `0.0`**, which is exactly the behaviour funduq has
always had; a deployment that serves NAT'd providers sets seconds, one where a
lost socket really means a lost provider leaves it, because then the caller
learns sooner.

**The runtime stopped dropping what it produced.**
`ProviderRuntime._report_output` took each event off its queue and, finding no
link, discarded it — so resume was unreachable whatever the wire carried, and
a reconnecting provider would have resumed a stream with a hole in it. It now
holds a bounded outbox per run. `max_buffered_events` (default 1024) is the
bound, and **a gap wider than it abandons the run rather than resuming it with
a hole**: funduq's grace then runs out and it records the
`provider_left_holding_it` it actually observed.

**The protocol carries enough for the two sides to agree where they were.**
`report` gained a `seq` — the provider's own count for that run, from 1, not
funduq's, which numbers everything on a run including its own events. After a
re-open the provider sends `resume` naming what it still holds; funduq answers
`resumed` with the last `seq` it accepted for each and the ones it is not
holding any more. The provider replays from the watermark and stops producing
for the rest.

And `reopen()` is what makes the machines sessions rather than connections.
The watermark is the one thing the funduq-side machine is the authority on,
and it could never have lived in a `FunduqLink` instance — that instance is
what gets thrown away on every blip. Which is the whole reason this landed
after the machines rather than before them.

`funduq/tests/test_a_blip_does_not_end_a_run.py` drives it end to end: drop
mid-run, reconnect, and the caller sees both what arrived before the blip and
what the provider produced while it was away — with `abandoned` still at zero.
The provider that does not come back is still recorded as abandoning, because
the grace forgives a blip and not a departure.

## What is not built yet

- **Resume on the completion half.** A dropped LLM link still ends its
  completions: `Chunk` carries no sequence and there is no `resume` for it.
  The shape is the agent half's, and the reason to wait is that a completion's
  caller is usually still holding an open stream, so what a resumed completion
  should look like to *that* caller is a question this has not answered.
