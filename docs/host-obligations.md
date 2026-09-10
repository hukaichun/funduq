# What a deployment owes

[What a deployment has to know](operational-limits.md) is the other half of
this page. That one is behaviour you have to plan around; this one is duties
you have to discharge.

They are not discharged the same way, and the difference is the only thing on
this page worth memorising:

| kind of duty | how you learn it | what happens if you skip it |
|---|---|---|
| core can be given it | it is a required argument | core refuses — loud, immediate, first request |
| core cannot observe it | a line on this page | nothing at all; you are silently wrong |

Every entry below says which kind it is. A list whose items look equally
weighty, half of them enforced and half on your honour, is worse than no list:
it teaches a reader that the enforced ones did not need saying, and therefore
that the honour ones are equally safe.

The strongest thing this repository can do for a duty is make it an argument.
`presenter_key` is the pattern — *"the transport must authenticate the caller
and hand the key to core"* is not a sentence you have to find and believe, it
is a parameter, and omitting it fails at the first request that carries a
chain. Where a duty can be built that way, it has been. What is left on the
honour list is what core cannot be given the ability to observe.

---

## Enforced: core refuses without them

### Authenticate the caller, and hand core the key you authenticated

`presenter_key=` on the AG-UI adapter, `presenter_key_of` on
`A2ARequestHandler`. A chain arriving without it raises `PresenterRequired`;
a key that is not the chain's last hop raises `InvalidChain`.

Verifying a chain is not authenticating a caller, and core cannot close the
gap alone — a door receives bytes, not a connection.
[Why this is the first thing on the other page](operational-limits.md#cores-caller-doors-are-not-independently-safe),
and why the presenter check is the whole of the anti-replay story, is there.

A deployment with no authenticating seat in front of its doors does not accept
chains at all. That is a working deployment, not a broken one — it is simply
one where no caller has an authority.

### Supply an identity key and a token signing secret

`CoreSettings.identity_private_key` and `CoreSettings.token_signing_secret`
have no defaults, deliberately. There is no environment reader in this package:
a deployment that keeps configuration in the environment reads it itself and
passes the values. Configuration is an argument here, never ambient state.

### Admit a provider before it can serve

`issue_ticket` mints a single-use ticket for one key; the provider signs
`provider_connect_payload` over it and funduq signs back. Anything else raises
`InvalidRegistration` — no proof, a ticket that was not issued to that key, a
ticket already spent or gone stale, a signature that does not verify.

`issue_ticket` **is** the admission decision. It is not a method to project
onto a wire for whoever can reach the door; how a ticket reaches a provider is
an enrolment channel, and that is on the honour list below.

### Carry a signed proof for an act on a bound thread

Cancelling a run, and answering a paused run's asks, are acts. On a thread
with an authority they need a signature from that authority or the serving
provider, over exactly this run and exactly the asks still open —
`InvalidCancel` and `InvalidResolution` otherwise. On an unbound thread there
is no authority to answer to and no proof is asked for.

### Present a chain that verifies

`InvalidChain`. Hop signatures, the hash links between them, and the rule that
a hop which dispatched and its successor must agree.

### Carry the token and the signature on a KYOK completion call

`KyokRejected`, with a status a gateway can pass through.

---

## On your honour: core cannot see whether you did

### Publish funduq's signing key at a funduq-level address

`Funduq.identity_public_key` is here and reaches exactly one audience: a
provider, through the connect handshake. A caller arriving at a door has no
path to it — not a published one, not an unpublished one.

**Not on the agent card.** The card is the provider's declaration of what its
agent is; funduq only relays it and swaps in its own `supported_interfaces`.
Hanging the intermediary's key off the provider's agent is the wrong owner,
and it shows: the same value would be printed on every card the deployment
serves, which is what a fact about funduq rather than about the agent looks
like.

Publish it at funduq's own address, naming no agent. That is already the shape
on the provider side, where funduq proves *funduq* unrelated to any agent, and
the caller side is the missing half. The caller gets the address for free:
`supported_interfaces[].url` is your door, so its origin is already in the
caller's hands.

Core cannot observe whether you did this, and cannot be given the ability to.
The cost of skipping it is nothing today and everything later: a signature
nobody can attribute is not evidence, so every future receipt funduq mints
([#278](https://github.com/hukaichun/funduq/issues/278)) is unverifiable by
the party it is for.

### Decide who may read

Core does not, as of contract revision 22. Reads are not acts, a chain records
acts, and authorisation belongs at the wire where a live channel exists.

What core offers is the question, not the verdict: `Funduq.parties_of(thread_id)`
returns the head, the provider serving the agent, and every key on the thread's
runs' chains — or `None` for a thread nobody bound, which names no parties at
all. Deriving that stays core's alone, because the chains are here and only
here are they verified. What follows from it is yours.

A deployment that keeps no rule of its own serves reads to whoever reaches its
doors. Nothing will tell you that is happening.

### Get the ticket to the provider

`issue_ticket` mints one; the channel that carries it to the party that should
hold it is not in this package and cannot be. Whoever can obtain a ticket for
a key can open a link as that key.

### Own the socket

Listening, dialling, TLS, framing, timeouts, retries, rate limits. funduq's
own code neither listens nor dials, and which protocol something arrived over
is not a thing core knows. The adapters return objects, not responses.

There is no wire in this package to reuse and none is coming: a published
method-to-endpoint mapping would be a wire authored here. **What you may call
survives a carrier swap and belongs here; how a call becomes an endpoint does
not and belongs to you.**

### Keep the record

Core never deletes a run, a thread or an event. Your own operations can —
retention policy, a dropped table, a restored backup — and nobody holds
anything funduq signed that would contradict a record that is simply gone. A
record removed and a record that never existed look exactly alike.

---

## What this surface does not yet offer

Stated here rather than left to be discovered, because until it exists a host
cannot discharge the duty by any means:

**A registered provider cannot authenticate at a door with the key funduq
already made it hold.** funduq proves a provider's key once, when the link
opens, and the open link is the credential from then on. But a provider
arriving at an AG-UI or A2A door is a caller like any other, and there is no
conventional way for it to present the key funduq already knows it by. So a
deployment wanting agent-to-agent delegation through its own front door must
invent a second credential for a party it has already authenticated once.

That is a question about the door's surface rather than about bytes, and it is
tracked in [#280](https://github.com/hukaichun/funduq/issues/280) with the rest
of this page.
