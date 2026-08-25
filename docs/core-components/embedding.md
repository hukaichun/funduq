# Embedding funduq

Part of [core components](../core-components.md).

funduq is a library before it is a service. Everything a serving layer
does over a wire, a Python process can do by calling methods — same
objects, same guarantees, no socket. This page is that surface.

```python
from funduq.core import Funduq
```

The package exports only `migrate` at the top level; `Funduq` comes from
`funduq.core`.

## The object

`Funduq(settings, broker=None)` builds the engine and the dispatch
machinery. **Settings are required and never read from the environment.**
Core is a library and does not own a process, so it is told its
configuration rather than finding it — the same rule that keeps transport,
liveness and authentication outside. A deployment that wants the
environment asks for it by name:

```python
funduq = Funduq(CoreSettings.from_env())
```

`broker` is the other injection point, and how dispatch timeouts are
changed — they are `RunBroker` constructor arguments rather than settings
(see [what a deployment has to know](../operational-limits.md)).

`await funduq.start()` must be called before any run is enqueued —
enqueueing on a stopped broker raises rather than silently accepting
work nothing would dispatch. It returns the ids of runs it reaped: runs
left `queued` or `running` by a previous process, which no longer have
anyone to finish them. `await funduq.aclose()` stops dispatch, cancels
tracked background tasks, and disposes the engine.

`await funduq.health()` is the readiness probe: database reachable, schema
at the expected revision, dispatch loop alive.

## Starting a run

```python
handle = await funduq.start_run(agent, run_input, thread_id=None, metadata=None)
```

`agent` is an `AgentRef` — a `(provider_key, name)` pair, because a name
alone is not an identity. `run_input` is the AG-UI-shaped payload the
provider will receive. Omitting `thread_id` opens a new thread; passing
one continues it.

This goes through the same machinery both caller doors go through
(`doors.open_run`, then `doors.dispatch`), so embedding funduq does not
buy a weaker entrance than a socket would: `metadata` is verified and
stripped of funduq's reserved keys, an actor chain is checked and its
head bound to the thread, a KYOK opt-in is honoured, the messages enter
the thread's history, and funduq's forwarded-props are built. **An agent
nobody is currently serving fails the run** with `agent_offline`, and
the handle's stream carries the terminal `RUN_ERROR` that says so — the
same answer either door gives, rather than a run queued into silence
behind an empty stream.

The `RunHandle` you get back carries `run_id`, `thread_id`, an
`async events()` iterator yielding each AG-UI event as the provider
produces it, and `cancel()`. It once carried an `is_live` flag too,
which was dropped for carrying no information: every handle core
constructed set it `True`. The live-versus-reconstructed distinction is
real but belongs to the A2A adapter, which decides it from its own
start result plus a broker lookup.

## Resuming and cancelling

```python
handle = await funduq.resume_run(run_id, run_input, metadata=None)
```

A resumed run **keeps its id**, because it is the same run. A run is the
agent's loop up to its natural exit, and a deferred call is a pause
*inside* that run — so the result goes back into the loop it suspended,
and the event log continues rather than starting over. That is why an
A2A task id stays valid across a pause.

The provider sees that pause as an ending: its stream really did return,
and its loop is gone. funduq holds the run's identity across the gap the
provider cannot hold, invoking the agent again and telling it which run
it is continuing.

So a run must actually be waiting for a result. An unknown run id raises
`LookupError`; one that is not suspended raises `NoPendingAsk` — a run
that already exited has no suspension to return to, and running it again
would put a second loop under the first one's id. That is a new run;
open one with `start_run`. `NoPendingAsk` is also what the loser of a
race sees when two results reach one pending ask.

`start_run` is the utterance entrance and `resume_run` is the result
one. There is no third — see [every seam has exactly two
entrances](../design-records.md#every-seam-has-exactly-two-entrances-an-utterance-or-a-result).

`funduq.cancel_run(run_id)` requests a cancel. It is synchronous and
returns whether the request was passed on, not whether the run stopped —
funduq asks, and records only what it then observes. See
[runs and cancels are requests](../mechanisms/requests.md).

## Three ways to address a run

A run is reachable by whichever of these the caller still has, and the
query surface exists so that losing the handle is never losing the run:

- **By handle** — the live event stream, for as long as the process that
  started it holds the object.
- **By id** — `get_run(run_id)` for the record, and
  `get_run_events(run_id, since_seq=0)` for the persisted event log. The
  `since_seq` cursor is what lets a reconnecting reader resume mid-run
  instead of replaying from the start.
- **By thread** — `get_thread_messages(thread_id)` for the folded
  history, `get_thread_snapshot` for the thread as a caller reads it
  back, and `get_thread_tree` for the thread plus every delegated
  descendant nested under `children`.

`active_runs()` lists the run ids dispatch currently holds in memory.
That is live state, so it is the one query that says nothing about runs
this process did not dispatch.

## Watching for change

```python
unsubscribe = funduq.on_change(callback)
```

Three event types exist, and they are deliberately coarse:
`RosterChanged()`, `LlmRosterChanged()` — neither carries fields — and
`RunStatusChanged(run_id, status)`. Events say *that* something changed;
reading the new state is the subscriber's own query.

Callbacks run **synchronously**, before the call that caused them
returns, and an exception a subscriber raises is logged and swallowed
rather than failing the operation that fired it. Keep them short.

## The roster

`list_agents()` and `list_llm_providers()` return what is registered,
each entry carrying `online` — meaning a provider is serving it right
now, which is a fact funduq holds rather than an inference from a
timestamp. `is_serving(agent)` answers the same question for one agent.
Entries whose provider has not checked in within
`stale_hidden_window_seconds` are hidden from the listings.

## Design records

Why this is shaped the way it is, and what it was shaped like first:

- [Liveness stopped being an inference](../design-records.md#liveness-stopped-being-an-inference)
- [A provider is its key, and has no other id](../design-records.md#a-provider-is-its-key-and-has-no-other-id)
