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

## Revision 6 — 2026-08-26

**The rule revision 5 announced is now the rule that runs.** 0.0.2 shipped
it bypassable, and this is the correction.

- **A hop cannot excuse itself from the dispatch check.** As shipped, the
  check skipped itself whenever the next hop carried a `dispatchedTo` of its
  own — meant to allow one dispatch following another, but the field is
  written by the party being checked, so the rule was opt-out. A branching
  party added the field and passed. A malformed value did worse: it slipped
  the check *and* cleared the pending dispatch, so the hop after it went
  unchecked too.

  The rule now reads: the hop after a dispatch must be signed by **the
  provider it named, or by the same key that signed the dispatch**. A
  witness may offer the same work onward because it is the witness — whose
  key signed the hop — not because the hop says so about itself. Both bypass
  shapes are pinned by tests, and a chain ending at a dispatch nobody
  answered stays legal.

*If you implemented against 0.0.2*: chains you were building are unaffected
unless you were relying on the escape, and a verifier that accepted a party
hop carrying its own `dispatchedTo` after somebody else's dispatch was
accepting a rewritten chain.

---

## Revision 5 — 2026-08-26

**A chain that was rewritten to leave someone out is now refused**, and the
number an installed package answers with is the number the vectors record.

- **`verify_chain` reads `dispatchedTo`.** funduq signs one hop per dispatch
  naming the agent it sent the run to, and an agent is `(provider_key,
  name)` — so that provider key is exactly the key that signs the next hop
  when the provider extends honestly. The field has existed for as long as
  the hop has and nothing read it, so the property it gives (a rebuilt chain
  contradicting itself) was *available* rather than enforced: a probe
  performed the comparison and the verifier did not. **A chain your
  implementation used to get away with may now be refused** — specifically
  one where a party hop follows a dispatch hop naming somebody else.

  Two shapes stay legal and are pinned by tests: a chain that **ends** at a
  dispatch nobody answered (the named party declined to extend, which is a
  break rather than a defect), and a **dispatch following a dispatch** (the
  same work offered onward without the first party signing).

  > **This rule did not hold as shipped — see revision 6.** The second
  > allowance was implemented by skipping the check whenever the successor
  > carried a `dispatchedTo`, which the party being checked writes. Anyone
  > who wanted past it added one. If you implemented against 0.0.2, the
  > refusal described above is not what you got.


- **The chain funduq stores is the chain it dispatched.** It used to store
  what the caller presented while the agent received that plus funduq's own
  hop, so funduq's records could not tell a run it had dispatched from one
  that reached it having passed no witness at all. Nothing on the wire
  changes for a provider; what changes is that the record now says which of
  the two it was.

- **A resume relays the run's own chain.** It used to relay the *answering
  party's*, with a fresh dispatch hop signed over it — so a provider that
  resolved its own agent's ask sent that agent a chain headed by the
  provider itself on the second round. One delegation now has one witness
  signature, and what an agent verifies does not change because somebody
  else answered its pause.

- **`CONTRACT_REVISION` was 3 while the vectors said 4.** Revision 4 is the
  entry that introduced the constant and it left the constant behind, and no
  test compared the two: the constant's value is in the fingerprint, so
  changing it forces *a* bump, but nothing required the bump to land on the
  same number. An installed package therefore answered one behind the
  vectors it was written against — the exact question the constant exists to
  answer. Both are 5 now, and a test holds them together.

- **The recorded pin was wrong in this file.** Revision 4 says
  `funduq-contract` is pinned `>=0.1.0,<0.2`; the declared bound is and was
  `>=0.0.1,<0.1`. The line is corrected below rather than quietly, because a
  changelog that misquotes a dependency bound is worse than one that omits
  it.

*For an implementation in any language*: no byte on the wire changes and the
vectors are untouched. What changes is that a verifier which accepted a
dispatch hop followed by the wrong signer was not implementing this
contract, and now has a test to say so.

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
  project can have runs through it. Now `>=0.0.1,<0.1` — this line said
  `>=0.1.0,<0.2`, which was never the declared bound; see revision 5.

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
