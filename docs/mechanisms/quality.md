# Provider quality counters

Part of [funduq's mechanisms](../mechanisms.md).

Capacity is a provider's own declaration — `max_concurrent_runs` is its
word, unverified. What funduq does instead of verifying is count what it
then observes, per provider, and judge nothing. The counters are the
material a serving layer, an operator, or a selection policy acts on;
funduq itself draws no conclusion from them.

## What is counted

For an agent provider, the discourtesies funduq can see from where it
stands: declining a run while claiming to have room (**misdeclared**),
not answering an offer inside the delivery window (**unanswered**),
answering an offer after funduq gave up waiting (**answered late**), and
two shapes of taking work and not returning it — **abandoned** and
**undelivered**.

Those last two are the same wrong seen with different certainty, which
is why they are two counters rather than one. **Abandoned** is certain:
the provider stopped serving while still holding the run, so it will
never come back. **Undelivered** is observed: the window passed and
nothing came back, and the provider may yet deliver. Merged, a reader
could not tell a provider that dropped three times from one that was
slow three times. Each run contributes at most one count, whichever
funduq observed first.

**Delivery is the measure, not motion.** A `RUN_STARTED`, a stream of
tokens, any amount of visible activity — none of it clears
`undelivered`. Only the run ending does. That is deliberate on two
counts: it is what "is this provider working" actually means, and it
keeps funduq from having to read an event's content to decide, which it
does not do anywhere else.

What is being judged is the **accept**. A provider that does not want
the work has two honest answers already in the protocol — decline (full
right now) or refuse (never) — and choosing *accepted* says it has taken
it. How long it then holds the run is its own business; taking the run
and delivering nothing is a different thing, and it is what this counts.
There is no exemption for a run whose LLM completion funduq is itself
relaying: a provider that accepted work it could not turn around said
yes when it could have said no.

For an LLM provider, the fate of each relayed completion: streamed to the
end (**completions**), ended in a structured refusal (**refused**), died
with anything else (**failed**).

## The stance

Counting is the other half of "funduq never records an outcome it has not
observed": what funduq *does* observe, it writes down. Nothing here is a
verdict on anyone's work — a refused completion may be the provider's
policy working exactly as intended — and no counter ever settles a run.

The agent-provider counters are, however, **the allowance**: when any
one of them reaches `provider_quality_tolerance` (default 3, `None`
disables it), the provider is withdrawn from service — the same judgment
for every counter, nobody holding a special seat. Withdrawal makes its
agents unserved, which is what then settles the runs it was holding, and
the way back is the front door: reconnect and register again, record
intact and still counting. The LLM-provider counters carry no such
consequence.

Beyond that, whether a count means "avoid this provider" or "this
provider's policy is strict" is the reader's judgment, made with context
funduq does not have.
