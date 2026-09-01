# The provider link

How a provider and funduq talk. This page is the settled design; where the
code differs today, the code is what has to move.

Everything that crosses the boundary is a pydantic model, no exceptions, and
each model is defined exactly once — in funduq-contract, the one package both
sides already depend on. These packages cover up to those models; everything
past them is the transport's.

## Before the link: the ticket

A provider submits its public key and receives a single-use ticket, valid for
60 seconds. How the ticket travels to the provider is the serving layer's
business — it is deliberately not on the link.

## Opening the link

The link opens with mutual proof, and nothing after it is signed: the open
link is the credential.

1. The provider opens its long connection carrying `Connect`: its public key,
   the ticket, a fresh nonce of its own, a proof —
   `sign(provider_connect_payload(funduq_public_key, ticket, provider_nonce))`
   — and, on the agent link, `maxConcurrentRuns`.
2. funduq verifies the proof, spends the ticket, and answers `ConnectOk`
   carrying `sign(funduq_connect_payload(ticket, provider_nonce))`, or
   `ConnectErr`. The provider verifies funduq's proof against the funduq key
   it has pinned.

Each direction's freshness has its own source: the provider's proof is fresh
because the ticket is single-use; funduq's is fresh because the provider's
nonce is new.

## After the link opens: requests and acks

Every funduq→provider operation is a request carrying an `id`, and every
request is acknowledged. There is no fire-and-forget in that direction.

| request | acknowledgement |
|---|---|
| offer (`id`, the run) | the verdict — accepted, declined or refused |
| cancel (`id`, the run id) | receipt: "the thread's handler was told" — never an outcome |
| complete (`id`, the completion request) | receipt, then the chunks, then an end or a failure, all under the same `id` |

The `id` exists because the acknowledgement may return on a different
connection than the request went down.

An acknowledgement is an intake decision, answered from state the provider
already holds — never gated on running anything. That is why the delivery
timeout is short: missing it means the link or the provider is broken, not
that it is thinking. funduq takes the run back and re-offers it; an
acknowledgement that arrives after that matches nothing and is answered
false, which is a guard, not a path. A provider that had actually taken the
run and lost its answer sees the same run offered again and simply accepts
again.

Every provider→funduq operation is a plain request with a response: register,
delete, thread messages, report, finish. The response is the answer; nothing
rides above the shapes.

## Runs, threads, handlers

- **A provider runs one handler per thread, and a thread has one active run**
  — by construction, not by discipline. The SDK runtime keys its handler
  table by thread.
- **funduq offers the next run of a thread when the previous one finishes.**
  While a run is live, the only second run a provider can receive on that
  thread is an interjection — a run whose caller declared `addressedRunId` —
  which bypasses the queue and goes to the running thread's handler. A
  provider that receives a second run therefore never has to guess which
  case it is in.
- **An interjection must name a live run on its own thread.** Naming a
  finished run, an unknown one, or a run on another thread is rejected at
  the door; if the named run settles before delivery, funduq fails the
  interjection rather than delivering a join to nothing.
- **Taking interjections is an opt-in.** A provider takes them by
  implementing the runtime's interjection hook; without it the runtime
  refuses them, so the caller learns the agent cannot be interrupted.
- **Events flow up as report/finish keyed by run id**: ordered within a run,
  unordered across runs.
- **Cancel is a request, not a command.** The run ends when the provider
  finishes it; funduq records that the ask was delivered, never an outcome it
  did not observe.
- **The link gone takes everything with it**: the agents come off the roster
  and the runs it held are failed. There is no resume.

## The shapes

Defined once in funduq-contract, imported by both sides:

- `Connect`, `ConnectOk`, `ConnectErr` — the opening exchange
- `Offer` and its verdict; `Cancel` and its `Ack`
- `Complete`, its chunks, and its end/failure markers
- `DeliveredRun`, `Registration` — the payloads the calls above carry

Every shape forbids unknown fields: a field the model does not declare is a
validation error, never silently carried or dropped.
