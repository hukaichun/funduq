# The dispatch trunk

Part of [core components](../core-components.md).

Four lanes, all network-free — each is a set of methods a serving layer
puts on whatever wire it chooses. This page describes how each lane
actually works, in order of what happens.

## The caller doors: AG-UI and A2A

Starting a run over AG-UI (`protocols/agui.py`) is a straight line:
verify the caller's metadata (an actor chain, if attached, is verified
here and a summary added), create or reopen the thread and run rows,
append the caller's messages to the thread, and check the agent is
currently served — an offline agent fails the run immediately with a
terminal event rather than queueing into silence. Then the run input is
built (below), handed to the broker, and the caller gets back a live
**event stream**: an async iterator that yields each AG-UI event as the
provider produces it — carrying **funduq's** thread id, which is the
authoritative one: a caller-supplied `threadId` funduq does not know is
not adopted, and the substitution rides back on every event rather than
happening silently (see
[conversation naming rights](../design-records.md#conversation-naming-rights-wait-for-a-caller-to-own-them)).
A run on a thread that already has one in flight
is accepted and queued behind it, its stream silent until its turn —
AG-UI has no "accepted, not yet worked on" state to answer with, and an
AG-UI client holds one session per thread, so the unusual second run is
queued rather than refused. Resuming a paused run is the same door with
a `resume` payload — the run keeps its id and its provider is invoked
again, targeting the thread's `input-required` run specifically. Two
callers answering the same question race, and the loser gets a
`ThreadSnapshot` of the thread as it now stands rather than a stream:
the question was already answered, so there is no second resume to
watch.

The A2A door (`protocols/a2a.py`) speaks JSON-RPC with method names read
off the A2A service descriptor (nothing hand-written, so an upstream
rename fails at import). `message/send` creates a thread and run through
the same repository calls, with one deliberate difference: an unknown
`contextId` is refused rather than replaced, because A2A's spec assigns
that id server-side while AG-UI's is client-chosen and required. Task
states are derived from run statuses; `referenceTaskIds`
records lineage; `tasks/cancel` is the one external cancel path — it raises `TaskNotCancelableError` on a task that has already ended, and otherwise answers `working` plus a marker saying the request is pending, because funduq asks a provider to stop and cannot make it. Every
message is kept: one whose `taskId` names the thread's paused
`input-required` task is the answer to its question and resumes that
run (status-guarded, so concurrent replies resolve to one resume); any
other message becomes a new queued run on the thread — including one
sent while a run is active, which waits its turn rather than being
merged, refused, or dropped.

## The translation: A2A becomes AG-UI before dispatch

Both doors converge on one function that builds the AG-UI
`RunAgentInput` the provider will see: thread id, run id, **this run's
own messages** — what the caller just said, appended to the thread's
record on the way past, not the thread's accumulated history (an AG-UI
client sends the conversation it holds; an A2A `message/send` carries
one message and funduq adds nothing to it) — and `forwardedProps` — the caller's free-form slot plus
funduq's own two additions (`caller`, `kyok`), built by a single shared
builder so a run's identity props are byte-identical whichever protocol
dispatched it. An agent therefore becomes A2A-callable without its
author writing any A2A: by the time the run reaches the provider, the
protocol difference has already been erased.

## The agent-provider lane: a run owns itself

`RunBroker` keeps the live state in memory: a `Run` object per active
run, a pending deque per **thread**, and a capacity bucket per provider
(declared limit vs in-flight count).

**Every run gets its own task the moment it is queued, and that task's
only wait is the run's own command queue.** Everything that can happen
to a run arrives there — a chance to be handed over, a cancel, an event
from the provider, a provider leaving, a verdict from a sweep — so
everything about one run happens in one order, decided by the run
itself. Nothing outside works out what a run's state means and then acts
on it; it says what happened, and the run decides.

Two refusals at the door of `enqueue_run`, both because accepting would
create a run nothing could ever finish: the broker must be started, and
**the agent must be served right now**. A run is only ever born with a
provider online — the caller-facing doors record `agent_offline` rather
than queue one — so the lane opens by offering rather than by waiting
for somebody to appear. Losing a provider afterwards is an ordinary
thing that happens to a live run; never having had one is not.

1. **Try.** Asked whether it can be handed over now, a run reads four
   things it owns or can see: it is not already dispatched, it is its
   conversation's turn, its agent is served, and its provider has a
   place. Any of them false means wait — whatever changes will ask
   again, and several reasons arriving at once are coalesced into one
   question. Arrival order is the only sequencing funduq imposes: a
   thread's utterances are offered in the order they came, and nothing
   wider than a thread is serialized. funduq does not pace a provider's
   conversation — running a new turn at once, holding it, or folding it
   into the turn in flight is the provider's own decision, made in the
   agent author's code (the design record
   [the thread gate is retired](../design-records.md#the-thread-gate-is-retired-funduq-does-not-pace-a-providers-conversation)
   records why funduq once decided this and stopped).
2. **Offer.** One awaited call carrying the claimed-run envelope, under
   a delivery timeout. The place is taken as the offer *leaves*, in the
   same breath as the check that there was one, and the run is recorded
   `offering` for the length of the answer — it is neither queued nor
   running, and both would be untrue to anyone reading the record. The
   provider answers accepted / declined-full / refused-permanently;
   timeouts and refusals are handled per [runs and cancels are
   requests](../mechanisms/requests.md). Anything that arrives during
   that answer — a cancel, typically — is read straight afterwards, in
   order, so funduq never asks a provider to stop a run it has not yet
   called running.
3. **Claim, then relay.** An accepted run leaves its conversation's
   queue (the next utterance gets its turn) and funduq starts calling it
   `running`. From there the same lane drains the same queue for the
   rest of the run's life: the provider reporting an event becomes a
   relay command (persist the event row, forward it to the caller's live
   stream); finishing the stream folds the run's outcome and writes the
   terminal status; a cancel request is forwarded to the provider's
   `cancel` and the lane keeps going until a terminal command actually
   arrives.

A lane ends on a terminal verdict, or on a cancel for a run no provider
took — nobody is working on it, so there is nothing to ask. Then one
funnel (`forget`) releases its state: it leaves its conversation's queue
so the next utterance gets its turn, its place goes back, KYOK bindings
die, listeners are told.

What is left of the sweep is two clocks and a nudge. It notes providers
that have not delivered what they accepted, gives up on queued runs
whose agent has gone unserved too long, and asks every waiting
conversation's head to try again. **It dispatches nothing and settles
nothing** — both clocks say what they observed into the run's own lane
and let the run decide.

## The LLM-provider lane: the completion relay

The KYOK door (`protocols/kyok.py`) is request-scoped, no queue. A call
arrives bearing the run's token; three checks run in order — the token
verifies and hasn't expired, the run it names is still live for that
agent, and the call is freshly signed by the agent provider's own key
over the token, a timestamp and the body hash. Then the run's binding
names an offering; the offering resolves to whichever connection
currently serves it (attach/re-attach mid-run just works, because the
binding never names a connection); and the provider's chunk iterator is
returned to the caller, wrapped in a counter that records how the stream
ended. Not attached → immediate fast-fail, because the calling agent is
holding a live stream open — queueing here would help nobody.

## One deliverer, and why that is load-bearing

Exactly one thing offers a run to a provider: **that run**. Nothing else
delivers, and nothing else settles — attaching a provider, freeing a
place, a sweep's clock running out, a caller cancelling all say what
happened into the run's own queue and let it decide. The call that hands
a run over has a single call site, reached only by the run whose it is.

That is an invariant, not a coincidence of the current code. Two parties
racing to offer the same run both plausibly succeed, and the run is
delivered twice, or claimed by one provider while the other's ack
arrives against a run already in flight — either way a run is lost or
duplicated, and neither is recoverable from the outcome funduq records.
It used to be an invariant *maintained*: the run had no owner until a
provider took it, so four parties took turns touching it and every pair
of them needed reconciling. Now it holds by construction.

Lanes running side by side do not weaken it. What they share is the
provider's capacity bucket, which is why a place is taken as the offer
leaves rather than when it is accepted — two runs reading an in-flight
count that only rises on acceptance would both find room that is not
there. Checking and taking are one function that does not await, so
there is no moment between them.

The same rule explains the two things `enqueue_run` refuses: a broker
that is not running, and an agent nobody is serving. Both would leave a
run `queued` forever, looking from every vantage point exactly like a
provider that is merely busy.

## The ack, and the ack that arrives too late

A provider's answer to an offer is three-valued, so the delivery call
returns either a boolean or a refusal carrying the provider's own
reason. A truthy answer claims the run; a falsy one is a transient
decline and the run stays queued; a refusal is permanent and fails the
run with that reason recorded verbatim.

Two clocks bound the wait. A single offer has a **delivery timeout**
(5 s): expiry counts an `unanswered` against the provider and hands the
run back to the queue, because a provider that did not answer has not
refused. An
agent left with **no serving provider** past its window (45 s) has its
queued runs failed `no_provider_took_it`, clocked from the later of when
the run was queued and when the agent went unserved. While a provider is
attached, a queued run waits indefinitely — the window times out the
absence of anyone to ask, not a provider's slowness.

A provider whose answer arrives after funduq gave up can still recover the
run, and the way it does so is by behaving as though it holds it:
reporting an event for a run it does not own is read as a late ack. funduq
accepts it only if the run is still unclaimed *and* the claimant is the
provider currently serving that agent, then counts an `answered_late`
and starts the pipeline. So a slow provider loses a quality counter, not
the work.

## Capacity is per identity, not per agent

The in-flight bucket is keyed by the provider's public key. One provider
serving five agents has one budget across all five, which is the same
answer funduq gives everywhere else: the key is the identity, and how a
provider arranges itself behind it is its own business.

**A provider has whatever room it said it has.** `declared` is its own
figure and the only capacity figure funduq has; the in-flight count is a
count, incremented when an offer leaves and decremented when the run
comes back or ends. A provider that declines while claiming to have room
is counted `misdeclared` — and that is all that happens. funduq does not
revise the declaration, and the run is simply offered again when
something changes. (A capped provider that delegates to its own agent
still deadlocks — see [the design
record](../design-records.md#self-delegation-deadlocks-a-capacity-capped-provider).)

funduq used to write its own conclusion into that count instead
(`in_flight = declared`, "treating it as full"). A count only knows how
to be incremented and decremented, so the phantom places that injected
never came back: **a provider that declared room for five and declined
once was capped at one, permanently.** Measured, and the reason the
count and the conclusion are no longer the same field.

The quality counters are not just a report — they are **the
allowance**: they say how much abnormality a provider is permitted,
and a provider whose counter reaches it (`provider_quality_tolerance`,
default 3, `None` disables; policy, so a setting) is **withdrawn from
service** — the same judgment for every event type and every provider,
nobody holding a special seat. funduq handles an abnormal provider
rather than cleaning up after one: nothing special happens to its
runs — queued ones stay in the queue like anyone's and, the agent now
unserved, travel the ordinary no-provider expiry road to a loud
failure; runs already in flight finish and report. The way back is
the front door: reconnect and register again, with the record intact
and still counting. (Before this rule, a provider that kept declining
was re-offered every sweep forever, inflating `misdeclared` into noise —
funduq#128. That was the old sweep's eagerness: a run is now asked to
try only when something has actually changed, and several reasons
arriving at once are coalesced into one question.) Providers that want funduq to pace intake
declare a real limit — that is what the declaration is for — and the
provider SDK keeps the default coherent: a runtime that claims no
limit accepts every delivered run, so it can never be branded abnormal
by its own transport plumbing.

## One substrate under both

A broker and a relay are deliberately different machines — one queues
and negotiates, one passes through — but each keeps the same roster:
a plain map from ref to connection where re-attaching under the same ref
replaces the old link (one connection per role), plus per-identity
counters. That table is extracted once as `LiveRoster` and composed by
both hosts, so the two lanes cannot drift apart; the register / attach /
detach ceremony above them is likewise stated once, in the facade's
`_Roster` base.

## Design records

Why this is shaped the way it is, and what it was shaped like first:

- [Dispatch was single-file, and the queue it blocked was everyone's](../design-records.md#dispatch-was-single-file-and-the-queue-it-blocked-was-everyones)
- [Wrapping an unknown event in `RawEvent` is quiet corruption](../design-records.md#wrapping-an-unknown-event-in-rawevent-is-quiet-corruption)
- [Liveness stopped being an inference](../design-records.md#liveness-stopped-being-an-inference)
