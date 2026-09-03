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
signs: registration and deletion (timestamped), the link-open connect
proof (challenge-answered — `sign_connect` over the pinned funduq key,
funduq's nonce, the provider's own nonce, and the names to serve, so the
proof names its recipient and cannot be relayed to another funduq), the
per-call KYOK signature, and the two singular acts on a bound thread's
run — `sign_resolution` to answer its ask, `sign_cancel` to ask that it
stop, each under its own tag so neither is ever the other. Each builder is the independent twin of funduq's, and
reproduces the published vectors byte-for-byte, deterministic signatures
included.

## The port and the worker

`FunduqLink` is the abstract port a transport implements: `deliver` a
run (handing it over — the verdict, accepted / declined / `Refusal`,
answers through funduq's `answer_offer` door on the same road reports
take, so a provider that accepts and streams in the same breath loses
nothing), `cancel` (acknowledged),
`report_event`, `finish_run`, `thread_messages`. `InProcessLink` is the
in-process transport (in-process is a transport, not a special case);
`ProviderRuntime` is the worker loop — one handler per thread, one active
run per thread by construction — that executes each agent's `run_stream`,
takes interjections through the opt-in `interject_stream` hook, and
reports events back through whatever link it is on. The shapes every
crossing uses are funduq-contract's; see [the provider
link](../provider-link.md).

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
