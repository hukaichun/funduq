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

## Revision 4 — 2026-08-25

**An installed package can now say which revision it implements**, and the
distributions carry the metadata a stranger needs.

- `funduq_contract.CONTRACT_REVISION` is a constant. Package versions and
  contract revisions answer different questions — a version says which
  release of one distribution you have, a revision says which set of bytes,
  settings and ports all of them agree on — and until now nothing installed
  could answer the second. It is part of the surface, so cutting a revision
  cannot forget it.

- **`funduq-contract` is pinned rather than named.** `funduq` and
  `funduq-provider-sdk` asked for it with no bounds at all, which would let a
  future incompatible release install itself under an old dependant. It is
  the one distribution both sides depend on, so every version skew this
  project can have runs through it. Now `>=0.1.0,<0.2`.

- **License, readme, classifiers and project urls** are declared on all
  three. Without them PyPI shows a blank page and "License: UNKNOWN", which
  for an enterprise reader is where evaluation stops.

*For an implementation in any language*: nothing here changes a byte on the
wire. The vectors are untouched.

---

## Revision 3 — 2026-08-25

**`funduq-llm-provider-sdk` is gone; serving completions is the `llm` extra
of `funduq-provider-sdk`.**

*What to change*: `pip install funduq-provider-sdk[llm]` instead of
`funduq-llm-provider-sdk`, and import from `funduq_provider_sdk.llm` instead
of `funduq_llm_provider_sdk`. Nothing else moved — the same classes, the same
names, the same wire shapes.

The two were 685 lines and 197, and the smaller imported nothing from the
larger but `ProviderIdentity`: identity is identity, whichever kind of
provider holds it. What kept them apart was dependency weight, which is the
same argument that shaped everything else here — and an extra answers it
better than a distribution does. `openai` drags httpx, anyio and a handful
more, and an agent provider still does not pay for any of it: the extra is
opt-in, and `funduq_provider_sdk.__init__` does not import the subpackage, so
the import cost is opt-in too.

It also settles a naming problem rather than solving one. With two packages,
the agent one silently owned the unqualified word "provider" and a reader had
to infer that. With one, "the provider SDK" covers both kinds honestly, and
the distributions line up by role: **contract**, **core**, **provider**,
and — when it exists — **caller**, which are the codebase's own words for the
two sides of a door.

This does not touch funduq's own separation of the two rosters. An LLM
provider still registers separately and is judged separately; that is core's
business, and this is a client library.

---

## Revision 2 — 2026-08-25

**A fourth package, `funduq-contract`, holds the bytes both sides sign.**

Core and the provider SDK each carried their own copy of the six signing
payloads, the actor-chain format and signature verification — the same
concepts under two sets of names (`resolve_payload` on one side,
`resolve_payload` on the other). There is one implementation now, and both
depend on it.

*For an implementation in Python*: import the payload builders and
`verify_chain` from `funduq_contract`. The six `*_signing_payload` names are
gone, along with `verify_actor_chain`, `new_actor_chain`,
`extend_actor_chain` and `InvalidActorChain` — the SDK's shorter names won,
because in a package called *contract* the word "signing" was saying what
"payload" already said. Core and the SDKs re-export the survivors, so
`from funduq.identity import resolve_payload` still works.

*For an implementation in any other language*: nothing changes. The vectors
are unchanged, and they are still the authority.

The duplication had a recorded justification: it once caught a payload
change 219 green tests had missed. That win is real and it is historical —
it happened six hours before `contract-vectors.json` existed, and a frozen
vector catches that same class against a single shared implementation.
Checked rather than assumed, by changing a domain tag in the one
implementation and watching `test_every_published_vector_is_what_this_
implementation_computes` go red.

`funduq-contract` is now part of the contract surface, which is why this
revision exists at all: adding a package that implementers depend on is a
contract change, and the fingerprint said so before anyone had to remember
to.

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
