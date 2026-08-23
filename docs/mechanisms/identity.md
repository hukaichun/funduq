# Identity is an Ed25519 keypair

Part of [funduq's mechanisms](../mechanisms.md).

A provider's identity to any funduq it connects to is its Ed25519 keypair —
not an account funduq issues. An agent is `(public key, name)`; an LLM
offering is the same pair; a name is deliberately not an identity and is
not exclusive. A short fingerprint derived from the key supports
human-friendly resolution, trust-on-first-use: two keys colliding on one
fingerprint is an error, not a merge. funduq has a keypair of its own
(`FunduqIdentity`, configured, never generated silently), so a provider can
pin the funduq it means to serve and detect an imposter before producing
anything worth stealing.

## What a provider signs, and what an open link makes unnecessary

Three payload families on this side, each under its own domain tag so a
captured signature for one purpose can never be replayed as another:

| domain tag | signed by | authorizes |
|---|---|---|
| `funduq-connect-provider` | connecting provider | opening a link |
| `funduq-connect-funduq` | funduq | answering a link-open |
| `funduq-kyok-call` | agent provider | one KYOK completion call |

(Three more belong to callers rather than providers —
`funduq-delegate`, `funduq-resolve` and `funduq-cancel` — and are in
[responsibility chains](responsibility-chains.md). Six in all.)

**Registering and deleting are not on that list, and used to be.** Four
families signed them — one per roster, one per verb — each re-proving
with a self-chosen timestamp that the caller held a key. But the key was
already proved, once, when the link opened: the handshake is a session
in everything but name, and those four were re-proving what it
established. They are operations on the open link now, and nothing signs
them.

Two things went with them. The agent card was never in a registration's
signed bytes, so a captured signature could re-register the same names
with a different card — there is no detached signature left to splice
one onto. And `funduq-connect-provider` no longer binds the names to be
served: they were in there so a captured proof could not be replayed to
serve a different agent, and a ticket issued to one key cannot be
replayed at all.

The KYOK call keeps its own signature because it is a different channel
— the agent provider calling *in*, not riding its own outbound link —
and it is the one payload that hashes the request body into the
signature, which is what a paid call deserves.

The KYOK call signs over a timestamp inside a freshness
window. Link-open does not: a self-chosen timestamp is replayable for its
whole window by anyone on the path, so opening a link answers a
**challenge the verifier chose** — funduq mints a single-use nonce, the
provider signs it together with its own nonce, the names it intends to
serve, and the funduq key it means to connect to — the recipient is in the
signed bytes, so a proof coaxed out by one funduq cannot be relayed to
attach at another — and funduq's answering signature (over both nonces,
under a distinct role tag so neither proof reflects as the other) is what
the provider verifies against its pinned funduq key. In-process connections authenticate
the same way, automatically — sharing a process is not a reason to skip
identity.

## Roster rules

Registration and deletion happen **on the open link** and sign nothing —
the link is the credential, and there is no way to reach either without
one. A link serves exactly the names it last registered, so registering a
smaller roster takes the omitted ones offline; their records stay,
readable as `online: false`. Deletion is refused while the name is in
use. funduq holds one connection per role: a re-attach under the same key
replaces the old connection; replicas are the provider's own concern
behind its single connection.

## Published as data

Every payload above is exported by the SDKs — the agent families by
`funduq-provider-sdk`, the LLM families by `funduq-llm-provider-sdk` — as
independent twins of funduq's implementation: neither SDK imports funduq nor
funduq them (the LLM SDK does share the provider SDK's keypair class,
because identity is identity). Each is pinned byte-for-byte in
[`contract-vectors.json`](../contract-vectors.json), with deterministic
signatures under a published test key. CI fails if a payload family goes
unpublished.

## Design records

Why this is shaped the way it is, and what it was shaped like first:

- [The verifier chooses the freshness](../design-records.md#the-verifier-chooses-the-freshness)
- [A provider is its key, and has no other id](../design-records.md#a-provider-is-its-key-and-has-no-other-id)
