# Actor chain

Part of [funduq's mechanisms](../mechanisms.md).

A chain answers "on whose behalf, through whose hands". Each hop is an
EdDSA JWT carrying exactly two things — the signer's own `actorPublicKey`
and a `prevHash`, the sha256 of the previous hop's full JWT, null on the
first. A chain carries keys and nothing else: no `subject` (retired — it
was the signer's own unverifiable claim), and **no time** — no `iat`, no
`exp`. Each hop is signed by the key it names; extending a chain appends a
hop that hash-links to the tail. The existing hops are never modified.

## Verification

Both sides verify independently — `funduq.identity.verify_chain` in
core, `funduq_provider_sdk.verify_chain` in the SDK — under the same rules:
every hop's signature under its own embedded key, and the hash linkage.
Rejected: a forged hop, a spliced or reordered chain. A chain in
[`contract-vectors.json`](../contract-vectors.json) pins both verifiers
byte-for-byte.

**A hop carries no expiry, by design.** Whether a *presentation* of a
chain is live is not a question either verifier can answer — it sees
bytes, not a live presenter — so proving a presentation live is the
authenticating seat's job (the door / gateway that has the live channel),
never the hop's. A run paused on a human for hours is therefore resumable
on the chain it started with: the chain never went stale, because
staleness is not a property a hop has.

## What a chain proves — and deliberately does not

Verification proves nobody rewrote the hops that exist. That is a narrower
statement than it looks, and the gaps below are load-bearing: two of them
have probes under `scripts/probes/` that are red on purpose.

- **A chain proves origin, not possession.** It proves the head's key
  signed hop zero. It does not prove that whoever is *presenting* it now
  holds that key — and a chain is not a secret: funduq relays it to the
  serving provider verbatim in `forwardedProps.actorChain`, deliberately,
  so the agent can verify for itself instead of trusting a summary funduq
  wrote. The provider therefore holds, in full, the thing a door reads to
  decide authority, and can present it back at a door for work the caller
  never asked for. `probe_a_provider_can_speak_as_the_caller.py` does
  exactly that; the run is accepted under the caller's head key and the
  record cannot tell the two apart. The answer is the presenter check
  below, and it is not built yet.

- **Completeness is not provable.** Signatures and links prove nobody was
  *inserted*, *reordered*, or *spliced in from another chain*. They never
  prove nobody was *removed*. A party holding `caller → A → B` can rebuild
  it as `caller → B`: it has hop zero's full token, so it hashes it and
  signs its own hop pointing at that hash. Nothing is forged, and the
  result reads exactly like a chain A was never on — see
  `probe_a_chain_can_be_branched.py`. If A is the hand that misbehaved, A
  is the hand that disappears.

- **Whom a key represents is not on the chain.** Hop zero asserts a key
  and nothing more, so there is no identity claim on a chain to be wrong
  about — and equally none to rely on. Translating a key to a person is a
  separate, opt-in disclosure (a voucher, signed by the party who actually
  knows), never a hop field. See
  [responsibility chains](responsibility-chains.md).

What does resist, and is asserted in the probes so it cannot be lost
quietly: **the head cannot be dropped** — a first hop carrying a
`prevHash` is refused, so truncation only runs from the tail backwards —
and **a hop from another chain cannot be grafted on**. So a branch can
only be built from hops the branching party genuinely received, and only
by erasing parties *between* the head and itself.

### A silent hop

A party that forwards a chain without extending it produces a chain that
still verifies — it has merely erased itself from the path. funduq does
not force anyone to sign and takes no position on whether it should have.

**Behind an authenticating seat this is now closed, and that changes what
the old wording claimed.** Forwarding `[A]` unextended means presenting a
chain whose last hop is A's; the presenter check compares the seat's
authenticated key against exactly that hop and refuses. So a party in front
of a seat cannot erase *itself* — it either signs, or it does not present.
The page used to describe self-erasure as an option that was merely
*priced*; where a seat exists, it is not an option.

Where no seat exists, `presenter_key` is None and nothing compares — the
mechanism is opt-in for a deployment that has one, and withdrawing authority
from callers who have no seat in front of them would be a different change.
There the old phrase still applies: the design record calls it **priced, not
compelled**, and the price is *the consumer's*, existing only where a
consumer's policy knows the expected call graph and controls something worth
withholding. KYOK is the worked example — an agent whose chain does not match
gets no completions. In an ordinary delegation tree there is no such
consumer, so there is no price: a receiving agent that sees `[A]` cannot tell
whether a hop is missing.

**What no seat closes is the erasure aimed at someone else.** A presenter
signs the hop it presents and cannot drop the head, so both ends are pinned
— and everyone *between* them can still be erased by a party that holds an
earlier hop's token and extends that instead. That is the branching case
above, it is a consequence of a hop naming only its signer and never its
recipient, and the dispatch hop below is what narrows it.

## The record keeps the head, not the path

funduq stores the **head key** on what needs an authority (a thread's
binding, a paused ask), and `runs.actor_chain` keeps the chain **as
dispatched**: every hop the caller presented, and then the one funduq signs
naming where it sent the run. The head answers "who answers for this"; the
chain answers "through whose hands", and nothing else on the record can.

It used to keep the presented chain alone, while the agent received the
longer one — so funduq's own books could not tell a run it had dispatched
from a chain that reached it having passed no witness at all, which is the
distinction the mechanism is for. The hop is signed at the door now, before
the run is created, so the same object is what the record keeps and what
the agent receives.

Keeping it makes the *claim* auditable: a branch is stored exactly as
branched, and what contradicts a branch is funduq's own dispatch hop, which
is now in the record rather than only in the copy handed out. Verification
reads it — the hop after a dispatch must be signed by the provider it named
or by the same witness offering the work onward, and nothing the successor
says about itself changes that.
Before both existed, a branch was not merely unprovable at verification
time — it was unnoticeable afterwards, because nothing was kept to notice
it against.

**Both are written once, when the run is created.** A run's
responsibility is fixed at its birth and there is one form of it, so
resuming a paused run replaces neither: the party that answers is not
taking the run over, and the run keeps answering to the head it was
opened under. That party is not unrecorded either — on a chained ask it
had to sign `funduq-resolve:{run_id}:{timestamp}` from the run's own
authority set, and that signature is kept in the run's metadata. It is a
stronger trace than a chain: a chain says who stood on the path, while a
signature is bound to *this* act by *this* key.

Changing a run's responsibility after birth is a separate question, and
one nothing here answers.

## The presenter check

`presenter_key` on every door, defaulting to None.
`probe_a_provider_can_speak_as_the_caller.py` was written red as its
acceptance test and is green.

funduq cannot authenticate a presenter: a door receives bytes, not a
connection. The seat in front of it can — the gateway that authenticated
the caller by SSO, mTLS, or a credential it issued, none of which a
provider holds. So the seat hands in the key it authenticated, and funduq
**compares** it against the chain's last-hop signer, refusing a chain
signed by anyone else at the tail.

The division is the point: authentication needs a live channel and stays
outside; the comparison belongs in core, where it is tested once and
pinned by vectors rather than reimplemented by every deployment —
comparing the chain's *head* instead of its *last hop* passes the exact
attack it is meant to stop.

Two consequences follow without new machinery. A provider that extends
honestly still passes, because it signed the tail — so delegation is
untouched and the delegator is named on the path. And when no key is
handed in, no head is recorded and the run is simply **unbound**, which is
already what a run carrying no chain is. Nothing is compelled: a caller
that wants none of this loses nothing it had. What is refused is a claim
the presenter cannot back.

**Core's caller doors are therefore not independently safe.** A
deployment that exposes them with no authenticating seat in front is
exposed, and that is a deployment invariant, not a setting.

## funduq signs as an identity too

funduq is an identity like any other (`FunduqIdentity`, the key providers
already pin), so it bears the same responsibility on a chain that a
provider does: `FunduqIdentity.dispatch_hop` appends one hop, signed with
its own key, each time it dispatches a run — an *extension* only, never a
new chain, because a request that carried none gets none and funduq
starting one would make itself the segment's head, which it is not. What
it buys:

- **"Routed through funduq" becomes verifiable.** A consumer that pins a
  funduq key can require its hops in the path; a chain that bypassed funduq,
  or was fabricated whole, doesn't have them. `verify_chain` hands back the
  hops it parsed, so that check is
  `any(h.actor_public_key == pinned and h.dispatched_to for h in result.hops)`.
  Both halves, always: `dispatched_to` alone is a claim anyone can write,
  and it is the pinned key that makes it a witness's.
- **Erasure becomes detectable**, because the hop names *the agent it
  dispatched to* (`dispatchedTo`). An agent is addressed as `(provider_key, name)`
  (`AgentRef`), and the provider half of that pair is the same key that
  signs the next hop when that provider extends. So the hop and its
  successor are checkable against each other: funduq said it dispatched to
  P, therefore the hop after funduq's must be signed by P. A branch breaks
  that relation — the hop says P and the next hop is signed by someone
  else — and dropping funduq's hop instead leaves a gap a consumer
  requiring funduq hops can refuse. The one party exempt from that relation
  is funduq itself, re-offering work nobody took; that exemption is a second
  *dispatch* hop, never a plain one, because a witness appears in a chain
  only as a witness. Without the field, the branch
  `caller → funduq → B` is indistinguishable from an honest direct
  dispatch. This is the one thing that reaches the completeness gap; the
  presenter check does not, because a branching party does not lie about
  who it is.
- **Which funduq signs it decides what it is worth.** Where both parties are
  providers on **one** funduq, every edge passes through a party to neither of
  them and the argument in
  [Responsibility chains](responsibility-chains.md#why-a-witness) holds as
  written — including between parties who know nothing about each other, since
  a provider is a key and there is no account to be in. Where each side runs
  **its own** funduq, the hop covering B's onward dispatch is signed by a key B
  operates: it is B attesting to B, and a chain that omits it still verifies
  for anyone pinning B's funduq, because that funduq is a legitimate signer
  that simply did not sign. This page used to call pinning several funduqs
  "the same act as pinning one". It is not — in one arrangement the signer is
  a witness, in the other it is the party — and that difference is the whole
  reason this hop exists. One funduq handing work to another has no chapter
  yet; this is the first question it owes an answer to.

Deliberately *not* carried on that hop: the run id. Anything riding inside
a chain is defeated by not attaching the chain at all, so it buys nothing
against a party that wants to erase the link, and for cooperating parties
querying both funduqs already answers the question. The dispatch target
earns its place for a different reason — it makes a *presented* chain
contradict itself.

## Design records

Why this is shaped the way it is, and what it was shaped like first:

- [A silent hop is priced, not compelled](../design-records.md#a-silent-hop-is-priced-not-compelled)
- [A chain hop carries no time](../design-records.md#a-chain-hop-carries-no-time)
- [A chain proves origin, not possession](../design-records.md#a-chain-proves-origin-not-possession)
