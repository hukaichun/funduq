# Contract changelog

What changed for anyone who wrote code against funduq, newest first.

The question this answers is "does my transport still work" — which commit
subjects, however well written, cannot. Each entry names one **contract
revision**, recorded in
[`contract-vectors.json`](contract-vectors.json)'s `contract` block together
with a fingerprint of the surface at that revision. A test recomputes the
fingerprint, so a change to the surface cannot land without a bump and an
entry here: writing the line is a condition of a green suite rather than a
courtesy someone remembers.

**The surface** is what an outside implementation would have to change its
own code to keep up with: the vectors themselves, `CoreSettings` fields and
whether each is required, the provider link's verbs, the A2A protocol
version and transport bindings, and whether each package ships its PEP 561
marker. Prose and internals are not in it — see `funduq/tests/contract_surface.py`, which
reads every part of it live rather than from a copy.

Nothing has been published yet, so nothing here is a migration burden on a
real deployment. It is a record from the beginning rather than one started
after the first person was hurt.

---

## Revision 1 — 2026-08-25

The first recorded revision. It is not a description of an empty starting
point: three contract changes landed just before it, and the reason this
file exists is that they were exactly the kind an adopter could not track.

- **A chain hop carries no time.** `iat` and `exp` are gone from an
  actor-chain hop, which is now `{actorPublicKey, prevHash}` and nothing
  else, and neither verifier checks an expiry. Both the chain vector and
  the `delivered-run` wire frame were regenerated. *An implementation that
  signs hops must stop stamping time; one that verifies must stop enforcing
  it.* (#180)

- **A dispatched chain carries one more hop.** funduq signs the dispatch it
  makes and names where it went, as `dispatchedTo: {providerKey, name}` on
  its own hop. A provider therefore receives its caller's hops unmodified
  **plus funduq's**, so a chain arriving at an agent is one longer than the
  one the caller sent. *An implementation that compared the received chain
  to the sent one for equality must compare a prefix instead.* (#184)

- **`identity_private_key` is required.** It had no default before only in
  the sense of being optional; a funduq without one now fails to construct.
  *A deployment must supply `FUNDUQ_IDENTITY_PRIVATE_KEY` — and the same key
  across restarts and across every process of one funduq, because providers
  pin it.* (#184)

Also in this revision, changing nothing for an existing implementation but
worth knowing:

- **A door can be told who is presenting.** `presenter_key` on every door,
  defaulting to `None`; when supplied it must equal the chain's last-hop
  signer. Omitting it changes nothing, which is why this is not a break.
  (#184)
- **The packages ship their types.** A PEP 561 marker in each, so an
  integrator's type checker stops seeing `Any`. (#187)
- **The metadata passthrough is stated as a promise**: everything outside
  the reserved keys is relayed verbatim. Behaviour unchanged; it was true
  before and now cannot quietly stop being. (#185)
