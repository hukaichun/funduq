# Writing a transport

funduq's core is network-free: it hands back objects and pure functions,
and putting them on a wire is a downstream job. This page is what that
job actually involves — the handshake in order, with the exact calls,
and the parts funduq deliberately leaves to you.

Everything a transport must produce or validate is pinned in
[`contract-vectors.json`](contract-vectors.json), so you can implement
this in any language without reading funduq's source.

!!! note "The orderings on this page are proposed for replacement"

    Everything below that is a *shape* is pinned by the vectors; everything
    that is an *ordering* — the handshake sequence, the three-valued answer,
    what a dropped link ends — is only pinned by this prose, and each
    implementation re-derives it. [The link protocol
    machine](link-protocol-machine.md) is the design for shipping those as
    code instead. Nothing in it is built; this page is still the contract.

## The opening handshake, in order

Five steps, and the order is the security property. This is the one
exchange that decides whether either side is talking to who it thinks —
and, since nothing a provider does to its own roster is signed any more,
it is the only place a key is ever proved. The payload bytes and why each
field is in them are in
[Contract and identity](core-components/contract-identity.md); what
follows is the call sequence a transport has to relay.

**1. funduq issues a ticket to the key, over a channel that is not the link.**

```python
ticket = funduq.issue_ticket(provider_public_key)
```

Single-use, valid for 60 seconds, destroyed by the handshake that answers
it. **Issuing is the admission decision** — a key with no ticket cannot
connect at all — so whoever calls this is the party that decides who may
serve here.

The ticket names the key it admits, and that is what makes it safe to
hand across a channel funduq does not control: a leaked ticket is
worthless, because only the named key can sign the answer, and a
stranger cannot burn it either (the name is matched *before* the ticket
is destroyed). It exists at all because a signature whose only liveness
is a self-chosen timestamp is replayable by anyone on the path — see
[the design record](design-records.md#the-verifier-chooses-the-freshness).

**Do not fetch it over the link being opened.** Core keeps the verb off
the link's operation set so it cannot be, and a ticket obtained over the
link would mean the link existed before anything authorised it. Which
channel you use instead is yours — an enrolment endpoint, an operator
console, out-of-band provisioning.

**2. The provider signs, naming the funduq it means to reach.**

```python
proof = identity.sign_connect(funduq_public_key, ticket, provider_nonce)
```

The provider contributes a nonce of its own and **names the recipient**:
the pinned funduq key goes into the signed bytes, so a proof one funduq
coaxes out cannot be relayed to attach at another. The verifying funduq
builds the payload with its *own* key, and a mismatch simply fails the
signature. Pass an empty string for a funduq with no identity.

What the link will serve is deliberately **not** in there. The names
used to be, so that a captured proof could not be replayed to serve a
different agent; a ticket issued to one key cannot be replayed at all.

**3. Open the link, and relay funduq's answer back.**

```python
answer = await funduq.attach_provider(
    provider,
    ticket=ticket, provider_nonce=provider_nonce, proof=proof,
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
is handed the answer **before the link is recorded open**, so a provider that
raises there never appears in the roster and never receives a run. The
provider SDK raises `WrongFunduq` for a mismatch. Both in-process links
implement the hook, so in-process goes through the identical ceremony
automatically — sharing a process is not a reason to skip identity.

If your transport verifies out-of-band instead, verify before sending
anything worth stealing:

```python
from funduq_provider_sdk import verify_signature, funduq_connect_payload
assert verify_signature(funduq_public_key, answer, funduq_connect_payload(ticket, provider_nonce))
```

There is no way to switch any of this off: a connection that exposes no
`sign_connect` and supplies no proof is refused.

**5. Publish, on the open link.**

```python
await funduq.register_agents(link, [{"name": "translator", ...}])
```

Nothing here is signed, and that is the point of everything above: the
key was proved once, when the link opened, and a per-operation signature
would only re-prove it. What this asks of you in return is the ordinary
thing — **an open link stays the party that opened it.** If your
transport can let someone else speak into an established connection, this
is where that becomes a roster it does not own.

An open link that has published nothing serves nothing; **not registered
is offline**, so the names a link serves are exactly the ones it last
published, and publishing a shorter roster takes the omitted ones off.
Deleting a record is the same shape — `funduq.delete_agent(link, name)`,
on the link that serves it — and it is refused for an agent with a
conversation behind it, which is the one guard a deletion still has.

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

**The answer is a receipt, and it must come from your own state.**
Whether the run arrived, whether there is room for it, and whether its
input is valid are all known the moment it lands; none of them requires
asking the agent anything. Answer then — the provider SDK's own runtime
does not await at all on this path, and the agent's code is nowhere near
it.

This is the one timing funduq depends on. It holds the next utterance of
the *same conversation* until this answer lands, which is how a thread's
delivery order survives a transport that guarantees none — and there is
no such guarantee to lean on instead: an offer is an independent call
with no position in it, so the only thing that can say "this one came
first" is that its answer came back first. A link that waits for the
agent to start turns that round-trip into the agent's startup time.
Nothing wider than the conversation waits: other threads, other agents
and other providers hand over meanwhile.

funduq cannot check this across a wire it does not own, so it is
recorded as [an assumption it rests
on](design-records.md#an-offers-answer-is-a-receipt-and-arrives-promptly)
rather than a rule it enforces — including what a violation costs, which
is bounded to the one conversation.

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
`TaskNotFoundError`, for the same reason. `cancel_task` on a task that
has already ended raises `TaskNotCancelableError`, which is what A2A's
own server does there.

**Pass `CancelTaskRequest.metadata` through.** A run on a thread that
bound an authority at birth can only be stopped by one of that thread's
authorities, and the proof — a signature over
`funduq-cancel:{run_id}:{timestamp}` — rides in that field. A2A's cancel
carries no message, but it does carry request metadata, so nothing is
invented and a standard client has somewhere to put it. Drop the field
and every cancel on a bound thread is refused; forge nothing, because
funduq verifies the signature, not the envelope. A cancel that carries
no authority for a bound run raises funduq's own `InvalidCancel` —
alongside `InvalidResolution` and `InvalidChain`, the family A2A
has no word for at all.

Caller mistakes come back in A2A's words too — an unknown `contextId`,
one belonging to another agent, a `kyok` opt-in naming an offering that
is not registered, or a message that will not build a run input all
raise `InvalidParamsError`, carrying funduq's own message so the caller
still learns which value was wrong. funduq writes no codes: the number
comes from the package's `JSON_RPC_ERROR_CODE_MAP`.

**Two are deliberately left as funduq's**, because A2A has no word for
either and one that means something else would be worse:

| escapes as | what it means | the answer that fits |
|---|---|---|
| `AgentNotFound` | the agent is the *endpoint*, resolved from the route before the adapter runs — an unknown one means the address does not exist | 404 on the route, not a JSON-RPC error inside a 200 |
| `ThreadQueueFull` | backpressure: the thread's buffer is full and the request was **not** accepted | 429, and say retry — never accept-then-expire |

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
