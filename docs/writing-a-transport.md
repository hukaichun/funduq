# Writing a transport

funduq's core is network-free: it hands back objects and pure functions,
and putting them on a wire is a downstream job. This page is what that
job actually involves — the handshake in order, with the exact calls,
and the parts funduq deliberately leaves to you.

Everything a transport must produce or validate is pinned in
[`contract-vectors.json`](contract-vectors.json), so you can implement
this in any language without reading funduq's source.

## The opening handshake, in order

Four steps, and the order is the security property. This is the one
exchange that decides whether either side is talking to who it thinks.
The payload bytes and why each field is in them are in
[Contract and identity](core-components/contract-identity.md); what
follows is the call sequence a transport has to relay.

**1. funduq mints a challenge.**

```python
challenge = funduq.issue_connect_challenge()
```

A single-use nonce, valid for 60 seconds, consumed on verification. It is
funduq's contribution to freshness, and it exists because a signature whose
only liveness is a self-chosen timestamp is replayable by anyone on the
path — see [the design record](design-records.md#the-verifier-chooses-the-freshness).

**2. The provider signs, naming the funduq it means to reach.**

```python
proof = identity.sign_connect(funduq_public_key, funduq_nonce, provider_nonce, names)
```

The provider contributes a nonce of its own and **names the recipient**:
the pinned funduq key goes into the signed bytes, so a proof one funduq
coaxes out cannot be relayed to attach at another. The verifying funduq
builds the payload with its *own* key, and a mismatch simply fails the
signature. The names are in there too, so a captured proof cannot be
replayed to serve a different agent. Pass an empty string for a funduq with
no identity.

**3. Attach, and relay funduq's answer back.**

```python
answer = await funduq.attach_provider(
    provider, agent_names,
    challenge=challenge, provider_nonce=provider_nonce, proof=proof,
)
```

`attach_provider` returns funduq's own signature over both nonces under a
distinct role tag, so neither side's proof can be reflected back as the
other's. **Relaying that answer to the provider is the transport's job** —
it is the half of the handshake that protects the provider, and it is the
whole point of funduq having a keypair.

A funduq with no identity key configured answers `None`. It cannot prove
itself, and only a provider that pinned a key treats that as a failure.

**4. The provider checks the answer before producing anything.**

A connection that exposes `confirm_connect(funduq_nonce, provider_nonce, answer)`
is handed the answer **before the attach commits**, so a provider that
raises there never appears in the roster and never receives a run. The
provider SDK raises `WrongFunduq` for a mismatch. Both in-process links
implement the hook, so in-process goes through the identical ceremony
automatically — sharing a process is not a reason to skip identity.

If your transport verifies out-of-band instead, verify before sending
anything worth stealing:

```python
from funduq_provider_sdk import verify_signature, funduq_connect_payload
assert verify_signature(funduq_public_key, answer, funduq_connect_payload(challenge, provider_nonce))
```

The proof is verified **before** the registered-names check, so an attach
that cannot prove itself never learns whether a name is registered. There
is no way to switch any of this off: a connection that exposes no
`sign_connect` and supplies no proof is refused.

## Reconnecting without killing your replacement

```python
funduq.detach_provider(public_key, connection=old_link)
```

Naming the connection is required, because cleanup that does not name
what it is cleaning up takes down the thing that replaced it: funduq holds
one connection per role, so a re-attach replaces the old link, and a
whole-key detach fired by the old link's teardown would take the live
replacement offline — exactly the case a reconnect produces. Scoped to
the connection, the cleanup of a replaced link is a no-op. The compare
and the withdraw run with no await between them, so a replacement
cannot slip in mid-detach.

Evicting a key outright — every agent and offering, whichever
connections serve them — is a different, deliberately louder verb:
`funduq.detach_all_for(public_key)`. Both detach forms, and
`detach_llm_provider`, are synchronous.

## Carrying a run down, and the ack back

An offer is one call carrying the run envelope, and the answer is
**three-valued**: accepted, declined-because-full, or permanently
refused with a reason. A transport that collapses this into one bit
re-creates a bug funduq already had — runs re-offered forever, reading as
`queued` from every vantage point while only the provider's log knew the
truth. Whatever framing you choose, all three values must survive it.

Everything else about how the answer travels is yours: framing,
correlation, backpressure, reconnect policy. funduq asks a question and
reads an answer; it has no opinion on the envelope.

## Serving the A2A door

Core hands back A2A's own messages — `AgentCard`, `Task`,
`TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent` — and nothing else. It
writes no JSON-RPC: no envelopes, no method names, no error codes. Mount
the package's own dispatcher over a thin handler:

```python
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher

class FunduqRequestHandler(RequestHandler):
    async def on_message_send(self, params, context):
        return await adapter.send_task(agent, MessageToDict(params.message))
    async def on_get_task(self, params, context):
        return await adapter.get_task(agent, params.id)      # None = not found
    ...

dispatcher = JsonRpcDispatcher(
    request_handler=FunduqRequestHandler(),
    enable_v0_3_compat=True,     # ← see below
)
```

`get_task` and `cancel_task` return `None` for a task that is not this
agent's, which is what the handler interface means by not-found; the
dispatcher turns it into the right error for the binding. An id the
caller sent that names nothing at all raises A2A's own
`TaskNotFoundError`, for the same reason.

!!! warning "`enable_v0_3_compat` is off by default, and forgetting it drops every v0.3 client"

    Measured against `a2a-sdk 1.1.2`: **which protocol version a request
    speaks rides the `A2A-Version` HTTP header, and no header means
    `0.3`.** With the flag off, `message/send` answers `-32601` and
    `SendMessage` without the header answers `-32009`. With it on, the
    dispatcher accepts the v0.3 names *and converts the shapes*
    (`"state": "completed"`, `parts` with `"kind"`), which a v0.3 client
    parses.

    That header is why this cannot live in core: core never sees one.
    funduq used to hand-write the method table here, and it answered
    v0.3's names with v1.0's shapes — a v0.3 client rejected the reply
    outright. Deciding a caller's version is the transport's job because
    only the transport holds the evidence.

## Relaying events

Dump typed events with `exclude_none=True`. A default dump injects
`timestamp: null` and `rawEvent: null` into the caller's stream; with
that flag the round trip is byte-identical to the input. Read only the
fields you are deciding on.

Validation is three-way, and a transport should not add a fourth. An
event whose `type` funduq knows is validated strictly, and a failure ends
the run. An event carrying a `type` string funduq does **not** know is
relayed untouched — funduq is a relay, and a provider on a newer AG-UI
must not be cut off by an event type funduq has not heard of. An event
with no `type` string at all still ends the run, because there is
nothing to relay it as.

So do not filter unknown event types on the way through, and do not
wrap them: see
[the design record](design-records.md#wrapping-an-unknown-event-in-rawevent-is-quiet-corruption)
for why `RawEvent` is the wrong shape for this.

## Prove it against the vectors

[`contract-vectors.json`](contract-vectors.json) publishes the seven
signed payload families, the two wire envelopes (`delivered-run`,
`delivered-completion`) and the actor-chain form, each with deterministic
signatures under a published test key. funduq's own suites replay them,
and so do both SDKs' — as independent twins that do not import funduq. If
your transport reproduces the vectors byte-for-byte, it is correct by
the same standard funduq holds itself to.
