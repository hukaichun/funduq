# funduq-provider-sdk

Part of [the SDKs](../sdks.md).

What an agent provider and funduq agree on, stated from the provider's
side. Dependencies are `cryptography`, `pyjwt`, `ag-ui-protocol` — no
transport library, and no funduq: not depending on funduq is what makes this
package a second opinion on the bytes rather than an echo, and a fitness
test keeps it that way.

## Identity and signing

`ProviderIdentity` wraps the Ed25519 keypair (generate, or load-or-create
from a key file so a restarted process keeps its identity; `public_key`
is the 64-char hex). Around it, builders for every payload the provider
signs: the link-open connect proof (challenge-answered — `sign_connect`
over the ticket funduq issued to this key, the provider's own nonce, and
the funduq key it means to connect to, so the proof names its recipient
and cannot be relayed to another funduq), the per-call KYOK signature,
the session delegation certificate, a chain hop, and the two acts on a
bound thread's run — `sign_resolution(run_id, answers)` to answer its
ask, naming every question and its `resolved`/`cancelled` decision, and
`sign_cancel(run_id)` to ask that the run stop, timestamped. Each act has
its own tag, so neither is ever the other. Registration and deletion sign
nothing: they happen on the open link, which already proved the key. Each
builder is the independent twin of funduq's, and reproduces the published
vectors byte-for-byte, deterministic signatures included.

## The port and the worker

`FunduqLink` is the abstract port a transport implements: `offer` a
delivered run (answering accepted / declined / `Refusal`), `cancel`,
`report_event`, `finish_run`, `thread_messages`. The base class states
the one translation every transport needs — funduq's claimed-run object
becomes a `DeliveredRun`, and an input that doesn't validate is a
permanent `Refusal`, not a transient decline. `InProcessLink` is the
in-process transport (in-process is a transport, not a special case);
`ProviderRuntime` is the worker loop that queues delivered runs, executes
each agent's `run_stream`, and reports events back through whatever link
it is on.

## The envelopes

`DeliveredRun` is both what the runtime consumes and the declared wire
frame (`model_dump(by_alias=True)` / `model_validate`); `CallerProps`,
`VerifiedActor` and `KyokForwardedProps` declare funduq's two
forwarded-props additions so no provider restates them — a restated copy
once drifted on one field's nullability and silently dropped verified
caller identities.

## Chain machinery

Both halves: `sign_hop` / `new_chain` / `extend_chain` to participate in
an actor chain, and `verify_chain` to police one — the twin of funduq's
verifier, same rules, no roster resolution, so an LLM provider or any
consumer can verify a delegation path without importing funduq.
