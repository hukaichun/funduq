# What a deployment has to know

The behaviour that decides how funduq is deployed and what an agent author
may assume — including what funduq does **not** do. Everything here is
checked against the code; where a page elsewhere says it better, this one
links rather than repeats.

## Core's caller doors are not independently safe

This is the first entry because nothing else here is close.

A door verifies the actor chain a caller attaches, copies its head onto
what needs an authority, and relays it. **Verifying a chain is not
authenticating a caller.** A chain proves the head's key signed hop zero;
it never proves that whoever presented it holds that key — and the chain is
not a secret, since funduq hands it to the serving provider verbatim so the
agent can verify it for itself. A provider therefore holds exactly what a
door reads to decide authority.

funduq cannot close that alone: a door receives bytes, not a connection, so
establishing who is calling needs a live channel core does not have. **A
deployment must put an authenticating seat in front of its doors** — a
gateway that authenticates the caller by SSO, mTLS, or a credential it
issued, and passes the key it authenticated as `presenter_key`. funduq then
refuses a chain whose last hop someone else signed.

Passing it is optional and omitting it changes nothing, because this is an
extension for a deployment that has such a seat rather than a new
requirement. A deployment that omits it is exactly as exposed as it was:
any party holding a chain can present it. See
[actor chain](mechanisms/actor-chain.md) and
`scripts/probes/probe_a_provider_can_speak_as_the_caller.py`.

Two things this does **not** close, deliberately:

- A party that extends the chain with its own key and then acts under the
  caller's head. That is visible and attributable, and whether the work was
  within what the caller asked is a question about scope, which funduq does
  not judge.
- A party rebuilding `caller → A → B` as `caller → B`. Nothing is forged;
  verification proves nobody was *added*, never that nobody was *removed*.
  What contradicts it is funduq's own dispatch hop.

## Pausing and blocking look the same to a user and are not the same to funduq

An agent waiting on a human has two ways to express it, and only one is
free.

- **Pause the run** (`input-required`). The run settles, funduq forgets it,
  and no clock runs against the provider. A run can wait on a person for
  hours or days.
- **Block inside the run.** The run is still one the provider accepted and
  has not delivered, so `undelivered_window_seconds` (default 1800) applies:
  when it passes, one **undelivered** is counted against the provider. At
  `provider_quality_tolerance` counts (default 3) the provider is withdrawn
  from service, taking every agent it serves with it.

Two agents that behave identically from a user's seat are therefore
completely different to funduq, and the difference is a declaration the
agent makes. See [provider quality counters](mechanisms/quality.md) for
what each counter means and why delivery, not motion, is the measure.

**Resuming restarts that clock rather than continuing it.** A resumed run
is claimed afresh, so it gets a whole new window — a run paused for three
hours resumes with the full 1800 seconds ahead of it, not with whatever was
left.

## Declaring no concurrency limit means never declining

`max_concurrent_runs=None` is the default in `ProviderRuntime`, and it is a
declaration funduq takes at its word: an unlimited provider that declines
is behaving abnormally, so a decline is counted **misdeclared** and offers
stop until it acts. The runtime therefore leaves its intake queue unbounded
in that mode, so it cannot decline by accident.

If an author wants pacing, the way to have it is to declare it —
`max_concurrent_runs=<n>` — not to decline while claiming to be unlimited.

## Quality counters are per-process and in memory

They survive a provider reconnecting, which `quality.md` says. They do not
survive **funduq** restarting: the roster holds them in memory and a new
process starts at zero.

For an embedded deployment that is the operationally decisive fact, because
of how it presents: a provider accumulates counts until it is withdrawn,
someone restarts the service, everything works, and it breaks again a few
days later. Nothing in the logs connects the two events.

## Topology

**A provider must be connected to the funduq its agents are registered
on.** `is_serving` reads that process's own roster, so a run for an agent
whose provider holds no link *here* is recorded `failed` / `agent_offline`
and is not queued — it does not wait for the provider to appear elsewhere.

**One funduq is one trust boundary, and delegation across boundaries works
today.** An agent served by one funduq delegates to an agent on another by
being a caller at that funduq's A2A door. It produces two runs linked by
lineage rather than one run spanning both, which is the intended shape:
cancelling the parent does not cancel the child, because the delegating
agent decides that — the same rule as funduq never deciding on a provider's
behalf.

**Running one funduq as several processes is not supported.** That is a
different thing from the paragraph above: it is horizontal scaling of a
single funduq. Do not read the missing feature as a limit on delegation; a
delegation tree has never had to fit in one process.

Measured on 2026-08-27, against two real OS processes sharing one database
with a load balancer that round-robins every caller-side call: **0 of 8
scenarios pass**, identically on SQLite and on Postgres. The fixture that
produced it lived at `scripts/probes/{node,cluster,probe_multiprocess}.py`
and is
[kept in git history at 6ed67be](https://github.com/hukaichun/funduq/blob/6ed67be/scripts/probes/probe_multiprocess.py)
rather than in the tree — it was retired in the same breath as the
measurement, because nothing ran it and a fixture nothing runs stops
working without anyone finding out, which is how the previous baseline came
to be quoted for months after it stopped being measurable at all.

The two findings that decide the shape of it are about the provider's
**link**, not about any run:

- **The link belongs to one process, and so does the ticket that admits
  it.** A provider that fetches its ticket through the load balancer and
  opens its link through the same balancer is refused outright: the ticket
  was minted in the other process's memory. Behind a balancer a provider
  cannot reliably connect *at all* — this fails at the door, not at the
  edges. It is also newer than it looks: when work was pulled rather than
  handed down, admission rode a token any node could verify from the shared
  secret, so this is a consequence of inverting dispatch that nothing
  measured until now.
- **A provider that re-attaches after its node dies is offered nothing.**
  The run is alive in the database and its provider is back, but the claim,
  the queues and the subscribers were process state on the node that died.

The other six are the ones a shared database makes obvious once you look: a
caller who lands on a node that does not hold the link has the run recorded
`failed` / `agent_offline` (the paragraph above, from the caller's side); a
booting replica reaps another node's live runs while their owner keeps
writing into them; an event reported at the wrong node is answered `False`
and the reporter is not told which node holds it; a stream opened at the
wrong node stays empty; and a SIGKILLed node leaves its runs `running`
forever, because nothing keys off a node being gone.

Those eight are the requirements list for the scaling work, whatever it is
eventually built on.

## Timing an embedder cannot reach

Three of the broker's timings are constructor keyword arguments rather than
`CoreSettings` fields:

| | default | what it bounds |
|---|---|---|
| `deliver_timeout_seconds` | 5.0 | waiting for a provider to take an offered run |
| `unserved_timeout_seconds` | 45.0 | how long a run stays queued with nobody serving it |
| `undelivered_window_seconds` | 1800.0 | the window in the section above |

They cannot be set through settings or the environment. Changing one means
constructing `RunBroker` yourself and passing it to `Funduq(broker=...)`.
That is a defect rather than a design — these are policy, the way
`provider_quality_tolerance` is policy — and it is on the list to fix.

A fourth one is not in that table because it *is* reachable, and it is the
one a deployment is most likely to need:

| | default | what it bounds |
|---|---|---|
| `CoreSettings.provider_grace_seconds` | 0.0 | how long a key whose link went away may still come back before the runs it holds are failed as `provider_left_holding_it` |

**Zero means what funduq has always done**: the link going away settles every
run that key was holding, at once. Set it to seconds if you serve providers
that reach you over connections they do not control — a provider behind NAT on
a consumer link is the party outbound dispatch exists for, and for it a
two-second drop is weather rather than an abdication. Leave it at zero where a
lost socket really does mean a lost provider, because then a caller learns
sooner. Nothing about it is a judgement funduq makes for you, which is why it
has no opinionated default.

Two things a nonzero value costs, both plainly: a caller whose provider is
genuinely gone waits that long before its run is recorded failed, and a
provider must be running an SDK new enough to buffer and replay — an older one
reconnects into a run funduq is still holding and reports a stream with a hole
in it. The provider SDK refuses that case rather than hiding it (see
`ProviderRuntime.resume`), but only for providers that use it.

Unlike the identity-layer timings funduq has been shedding, these cannot
simply be removed: they model real waiting, and detecting a provider that
has stopped answering needs a clock. The fix is to move them out to the
embedder, not to delete them.
