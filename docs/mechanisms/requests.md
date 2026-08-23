# Runs and cancels are requests

Part of [funduq's mechanisms](../mechanisms.md).

Everything funduq sends a provider is a request, never a command. funduq
cannot make a provider take a run, and it cannot make one stop — it can
only ask, watch what happens, and record exactly that.

## Offering a run

A queued run is *offered* to its agent's provider in arrival order, head
of the queue first — arrival order is the one sequencing funduq owns, and
[the thread gate is retired](../design-records.md#the-thread-gate-is-retired-funduq-does-not-pace-a-providers-conversation),
so a sibling utterance is offered as soon as it reaches the head whether
or not the previous turn is still running. The provider answers with one
of three values:

- **accepted** — the run is claimed and its events start flowing;
- **declined** — "full right now"; funduq keeps the run queued and offers
  again when something changes, for as long as the agent has a provider
  attached. Only an agent left *unserved* past a grace window (a broker
  argument, 45 s by default) has its queued runs given up on, failed as
  `no_provider_took_it` — a timeout on the absence of anyone to ask, not
  a judgment;
- **refused** — permanent: this provider will never accept it (an agent
  it no longer serves, an input that can never validate). funduq fails the
  run with the provider's own reason recorded verbatim and stops
  re-offering. funduq invents no reason of its own — the annotation is the
  provider's.

The three-valued answer exists because collapsing decline and refusal
into one bit left runs re-offered forever, reading as `queued` from every
vantage point while the provider's log alone knew the truth.

## The wait for that answer is a state, and it belongs to one agent

Between the offer leaving and the answer arriving, the run is
**`offering`**: funduq no longer has it and no provider has accepted it,
so neither `queued` nor `running` is true, and a caller reading the
record during that window has to be told something. (To A2A it is still
`submitted` — nothing is being worked on yet.) A declined offer puts it
back to `queued`, which is the only transition that does not go through
the status machine, because a run is otherwise never *moved* to queued —
it is born there.

Two things happen the moment the offer leaves rather than when it is
accepted, and both are the same idea: **the run has an owner from
dispatch onwards.**

- **Its place on the provider is spent.** A provider that declared room
  for one gets one offer, not one *accepted* run plus however many
  offers were in flight while it was thinking.
- **A cancel arriving now queues behind the pending answer** instead of
  being decided in funduq's favour. If the provider took the run it is
  asked to stop; if it declined, the run ends here. What cannot happen
  any more is both — funduq recording `cancelled` and handing the same
  run over a moment later.

Everything that happens to a run happens in one order, because **one
thing applies all of it: the run itself.** Its lane exists from the
moment it is queued and its own command queue is the only thing that
lane ever waits on, so a cancel arriving during an unanswered offer is
simply read after the answer — not raced against it, and not decided by
whoever happened to be touching the run at that instant.

**Waiting for an answer holds up one conversation and nothing else.** A
thread is the pipe whose delivery order funduq guarantees, so a thread's
utterances go over one at a time, in the order they arrived. Everything
wider hands over side by side: two conversations have no order between
them even when they share an agent, a provider and a caller. Each run
does its own waiting, in its own task, from the moment it is queued.

The order matters because of who does the sequencing. funduq imposes no
turn-taking — a provider decides whether to run a new utterance at once,
hold it, or fold it into the turn in flight — but a provider that *does*
take turns can only take them in the order things reach it. Deliver two
utterances of one conversation at once and its own sequencing locks in
an order nobody chose, invisibly. So funduq owes sequence, not pacing.

And the only thing that can say "this one came first" is that its answer
came back first. An offer is an independent call carrying no position,
and [the transport contract](../writing-a-transport.md) promises no
ordering — nor could funduq define one to promise, since two offers it
issues concurrently reach the wire in whatever order their own work
finishes. **What makes this cheap is that the answer is a receipt.** A
provider decides accept / full / never from what it already knows when
the run lands; the provider SDK's runtime does not await at all on that
path. So the wait is one round-trip, not the agent's work, and it is
spent only when a second utterance of the same conversation is already
waiting — which means it arrived faster than a round-trip.

It used to hold up everything, because one loop offered to one agent at
a time — and then, briefly, one agent's whole roster of conversations,
which was the same mistake at a smaller size. See [the design
record](../design-records.md#dispatch-was-single-file-and-the-queue-it-blocked-was-everyones).

!!! note "One active turn per conversation is the provider's to enforce"
    A conversation can only be generating one turn at a time — that is a
    property of the medium, not a rule funduq invented — and an
    interjection is not a second turn but something injected into the
    one in flight. Resolving that is the agent's own scheduling
    ([`serialize_per_thread`](../sdks/provider-sdk.md) is the
    off-the-shelf form), and funduq deliberately does not do it for
    them. What funduq owes is that the utterances arrive in order for
    that scheduling to be possible at all.

## Cancelling a run

A cancel is relayed to the provider as a request. The provider may comply,
finish normally anyway, or ignore it; funduq keeps relaying whatever the
run emits and records the outcome it then observes — a claimed run is
never marked `cancelled` at request time, because funduq never records an
outcome it has not observed. The one immediate cancellation is a run
still queued: no provider has it, so there is no outcome funduq could be
pre-empting. The same rule holds everywhere: statuses are observations,
not intentions.

## What a run's final status is

One funnel settles every run that reached a provider
(`handlers._handle_finish`), and the conditions are tried **in this
order** — the first match wins:

| condition | status | recorded metadata |
|---|---|---|
| the stream ended on an interrupt outcome | `input-required` | the pause payload, interrupts preserved |
| the provider sent `RUN_FINISHED` | `completed` | — |
| a cancel had been requested | `cancelled` | — |
| none of the above | `failed` | `provider_stream_ended_without_finishing` |

The order is the mechanism, not an implementation accident. **A provider
that ignores a cancel and finishes is recorded `completed`**, because
`RUN_FINISHED` is tried before `cancel_requested` — funduq asked, the
provider declined to stop, and the run's own output is what happened. A
pause outranks both: an interrupt outcome arrives *on* a `RUN_FINISHED`,
so the run that stopped to ask a human is not filed as one that finished.

Runs that never reach that funnel are failed with a reason instead: an
agent with no attached provider (`agent_offline`), a queued run whose
agent went unserved past its window (`no_provider_took_it`), a claimed
run whose provider stopped serving while still holding it
(`provider_left_holding_it`), a paused run nobody answered before its
deadline (`paused_no_resume`), a permanent refusal, and a malformed
event — one whose known AG-UI `type` fails
validation, or one with no `type` string at all. An event whose `type`
is a string funduq merely does not recognise is not malformed: it is a
newer AG-UI's event, and funduq relays it untouched — whether to skip it
is the caller's decision, never the relay's.

A run recorded `failed` that never emitted its own `RUN_ERROR` gets one
synthesized, persisted and relayed, so a caller can tell failure from an
agent with nothing to say — including runs the broker no longer tracks
when the verdict lands (a stale pause reaped as `paused_no_resume`, an
orphan reaped at startup), whose event is appended to the record
directly since no stream is left to relay it to. A run that already
reported its own is left alone.

That holds for every run the broker still tracks. **It does not hold for
a paused run failed as `paused_no_resume`**: the broker forgot the run
when it paused, so there is no stream left to push a terminal event
onto, and the status changes in the database with nothing said. A caller
watching the stream sees it simply stop after the `RUN_FINISHED` that
asked the question. That is the same silence the synthesized `RUN_ERROR`
exists to prevent, and it is a gap rather than a decision.

## Silence is not a verdict

**How long a provider holds a claimed run is the provider's own
business.** funduq does not pace a provider's work, and it does not read
quiet as death: an agent's loop is silent for most of its life by
construction, because the model call it is waiting on is the segment
nothing can be injected into (see [the agent loop](../agent-loop.md)).

There was a clock here once — `run_stall_timeout_seconds`, 120s — that
failed a claimed run for going quiet. It blamed slow providers for doing
nothing wrong, and it blamed runs whose silence funduq itself was
causing, by holding their KYOK completion while the LLM provider worked.

What funduq judges instead is whether a provider is **behaving
abnormally**, and it reads that from **delivery**, never from motion. A
provider that stops serving while still holding a run took work and
never ended it: the run is failed at once, and the same fact records
`abandoned` against it. A provider still attached that has not delivered
what it accepted inside the window records `undelivered` — a count
against the provider, with the run left entirely alone. Neither counter
ever settles a run on a clock; the allowance withdraws the provider, and
withdrawal is what then settles what it was holding. See [provider
quality counters](quality.md).

A provider that stays attached and holds a run indefinitely keeps it
indefinitely. That is the same answer the queue lane already gives ("a
run whose agent *is* served stays queued indefinitely"), and the party
with a stake has the lever funduq does not need: the caller can cancel.

## Cancelling is not a state a caller can read as final

`cancelling` is an **active** status, alongside `queued`, `offering`,
`running` and `input-required`. It means funduq has passed the request on and is still
relaying — not that the run stopped. It has no A2A equivalent, because
A2A's `TASK_STATE_CANCELED` asserts an outcome funduq has not observed
yet; only the settled `cancelled` maps to it.

While a run is cancel-requested, a KYOK completion call naming it is
refused. funduq stops funding work it has been asked to stop, which is the
one consequence a cancel has that does not depend on the provider
agreeing to it.

## AG-UI has no cancel signal

Measured against the installed `ag-ui-protocol`: `EventType` has no
cancel member, and a run's terminal events are `RUN_FINISHED` and
`RUN_ERROR` only, whose outcome is success or interrupt. There is no
cancelled event and no cancelled outcome.

So the AG-UI door has no cancel entry point, and A2A's `tasks/cancel` is
the only cancel a standard client can send. funduq does not invent one —
inventing an event type would be exactly the forced protocol deviation
the [integration contract](../integration-contract.md) rules out. It also
explains the asymmetry in what funduq reports: a `failed` run gets a
terminal `RUN_ERROR` because AG-UI has one to send, and a `cancelled`
run gets nothing, because there is no such event and the only party who
would read it is the one who asked.

## Design records

Why this is shaped the way it is, and what it was shaped like first:

- [An offer's answer is a receipt, and arrives promptly](../design-records.md#an-offers-answer-is-a-receipt-and-arrives-promptly)
- [Dispatch was single-file, and the queue it blocked was everyone's](../design-records.md#dispatch-was-single-file-and-the-queue-it-blocked-was-everyones)
- [Silence about a verdict funduq has reached is a bug](../design-records.md#silence-about-a-verdict-funduq-has-reached-is-a-bug)
- [Enforcing cancellation produced a family of bugs](../design-records.md#enforcing-cancellation-produced-a-family-of-bugs)
