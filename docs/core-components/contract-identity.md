# Contract and identity

Part of [core components](../core-components.md).

Signing lives with whoever holds a key; **core's half is verification**.
This page describes how each verifying piece works.

## Signed payloads

Every signed operation reduces to the same primitive: build a canonical
byte string, verify an Ed25519 signature over exactly those bytes. The
payloads are colon-joined text under a **domain tag** —
`funduq-kyok-call:{token}:{timestamp}:{sha256 of body}`,
`funduq-connect-provider:{pinned funduq key}:{ticket}:{provider nonce}`,
and so on for the three families — the tag first, so a signature captured
for one purpose is meaningless for another. Timestamped families are
accepted within a ±60s freshness window of funduq's clock.

**A provider's roster acts are not among them.** Registering and deleting
were four families once, one per roster and verb, each re-proving with a
self-chosen timestamp that the caller held a key that had already been
proved when its link opened. They are operations on the open link now
(see [the handshake](../writing-a-transport.md)), and nothing signs
them.

## Link-open tickets

Connect authentication cannot ride a timestamp (self-chosen freshness is
replayable for its whole window), so it answers a ticket funduq issued.
`issue_ticket(public_key)` mints a random single-use value and remembers
it **with the key it admits** and its issue time; the connecting provider
signs
`funduq-connect-provider:{pinned funduq key}:{ticket}:{provider nonce}`
— the first field names the recipient, so a proof one funduq coaxes out
cannot be relayed to attach at another.

Verification matches the ticket's key against the connecting key
**first**, then destroys it, then checks the signature against a payload
built with this funduq's *own* key. That order is load-bearing twice
over: a leaked ticket is useless to anyone but the key it names, and a
stranger cannot spend someone else's admission with a garbage proof —
which a version that destroyed first allowed, as a denial needing no key
at all.

funduq answers in kind: `attach` returns its own signature — the
`FunduqIdentity` keypair over `funduq-connect-funduq:{ticket}:{provider
nonce}` — for the transport to relay, and hands it to any connection
exposing `confirm_connect` before the link is recorded open, which is
where a provider checks it against the funduq key it pinned and refuses
an imposter. In-process connections go through the identical ceremony
automatically: ticketed, verified, and answered. A funduq with no
identity configured answers nothing — it cannot prove itself, and only a
pinning provider treats that as a failure.

Issuing a ticket is **not** an operation on a connection and cannot
become one: one fetched over the link would mean the link existed before
anything authorised it.

## Actor chain verification

A chain is a list of JWTs. The verifier walks it in order: for each hop,
read the signer's public key out of the (not yet trusted) payload,
verify the JWT's signature under exactly that key, then check the hop's
`prevHash` equals the sha256 of the previous hop's full text, and that
the `subject` never changes. Expiry is enforced on the **last** hop
only — earlier hops are provenance, not standing authorization. The
result is the subject plus each signer's key in order; funduq additionally
resolves each key against the roster to name registered agents, which
the SDK's twin verifier deliberately does not (it has no roster).

## Envelope models

Every structure funduq puts on a wire is a pydantic model with camelCase
aliases: `model_dump(by_alias=True)` **is** the frame a transport
carries, `model_validate` rebuilds it. `models.py` declares the refs and
the claimed-run shape; `props.py` declares the verified-caller props
model and assembles both forwarded-props additions in one place for both
caller doors (the KYOK props model itself lives with its mechanism in
`kyok.py`). Translation
from funduq's internal objects to the delivered forms is stated once, as
classmethods on the delivered models, read by attribute so no import
crosses the boundary.

## The twins and the guards

Everything above is deliberately implemented twice: the provider SDKs
carry independent twins — payload builders, a chain verifier, the
delivered envelopes and props models — and neither side imports the
other, so each suite is a second opinion on the bytes rather than an
echo. Agreement is pinned by
[`contract-vectors.json`](../contract-vectors.json): inputs → exact
payload bytes → deterministic signatures under a published test key,
plus a fixed-time chain and the canonical wire frames, consumed by all
three test suites and replayable in any language. Two CI guards keep the
set complete — every domain tag must have a vector family, and the SDKs
must validate every structure funduq puts on the wire — because both gaps
were shipped and paid for before the guards existed.
