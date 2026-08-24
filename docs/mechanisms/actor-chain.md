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

Both sides verify independently — `funduq.identity.verify_actor_chain` in
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

Verification proves nobody rewrote the hops that exist. Two things it
does not prove, by design:

- **The first hop is a claim.** The subject is asserted by whoever signed
  hop zero; funduq cannot know how that party came to trust it. The
  weakness closes where the verifier *is* the subject — in KYOK's
  personal-key deployment, the party verifying the chain knows which
  first-hop key is genuinely its own agency.
- **A silent hop is an omission, not a break.** A party that forwards a
  chain without extending it produces a chain that still verifies — it
  has merely erased itself from the path. funduq does not force anyone to
  sign, and takes no position on whether it should have: whether the full
  chain must be carried at every hop is a convention the agent providers
  and LLM providers involved agree between themselves. funduq carries and
  verifies whatever chain arrives, and leaves what to accept to the
  parties.

funduq verifies chains and relays them; it never signs on anyone's behalf
and never vouches for a subject.

## funduq signs as an identity too — **not implemented yet**

> **Status: decided direction, no code.** Tracked here so the gap is
> visible. The hop-expiry semantics that used to block it are gone (a hop
> now carries no time), so the old blocker is cleared; what remains is
> implementation.

funduq is an identity like any other (`FunduqIdentity`, the key providers
already pin), so it can bear the same responsibility on a chain that a
provider does: append one standard hop, signed with its own key, each
time it dispatches a run — no new claim, no role marker, no format
extension. What that buys:

- **"Routed through funduq" becomes verifiable.** A consumer that pins a
  funduq key can require its hops in the path; a chain that bypassed funduq,
  or was fabricated whole, doesn't have them.
- **A silent hop becomes structurally visible.** With funduq signing every
  dispatch, a fully-signed chain alternates funduq and provider hops; a
  provider that forwarded without signing leaves two consecutive funduq
  hops — witnessed, without funduq naming anyone.
- **Federation needs no extra design.** A chain crossing several funduqs
  carries each funduq's own hops; consumers pin the funduqs they trust, the
  same act as pinning one.

What used to block it — hop-expiry semantics — is resolved. funduq's hop
would often be the last hop at delivery time, and when verification
enforced expiry on the last hop, a chain read again late in a long run
would have failed on funduq's own stale hop. A hop no longer carries any
expiry, so that failure mode is gone; the mechanism is now only waiting on
being built.

## Design records

Why this is shaped the way it is, and what it was shaped like first:

- [A silent hop is priced, not compelled](../design-records.md#a-silent-hop-is-priced-not-compelled)
