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
whether each is required, the provider link's verbs, the link protocol's
frames and every machine's verbs on both link kinds, the A2A protocol
version and transport bindings, whether each package ships its PEP 561
marker, and every public name `funduq_contract` exports with the shape it
exports it as. Prose and internals are not in it — see `funduq/tests/contract_surface.py`, which
reads every part of it live rather than from a copy.

This started before anything was published, which is the point: it is a
record from the beginning rather than one begun after the first person was
hurt. Revisions 1–5 predate any release. From `funduq-contract` 0.0.1
onwards a stranger can install a version and be wrong about it, so the
entries below say what to change and not only what moved.

---

## Revision 10 — 2026-08-27

**A dropped socket stops ending a run** ([#214](https://github.com/hukaichun/funduq/issues/214)).
Three things had to move together, which is why it was never a keyword
argument.

- **`CoreSettings.provider_grace_seconds`, default `0.0`.** How long a key
  whose link went away may still come back before the runs it holds are given
  up on. Zero is what funduq has always done — the link going away settles
  them at once — so **nothing changes for an existing deployment that does not
  set it.** Core stopped welding two facts together: the roster still loses a
  key the moment its link goes (nothing new is handed to somebody who is not
  there), but what it is already holding is no longer given up on in the same
  breath. `RunBroker.expire_gone_providers` is the clock, and it is a clock
  over a fact funduq owns — how long since *this link* went away — not a
  deduction about how the provider is doing.

- **`FunduqLink.report_event` takes `seq`**, keyword-only and defaulted:
  `async def report_event(self, run_id, event, *, seq: int | None = None)`.
  *An existing implementation adds `*, seq: int | None = None` and ignores
  it* — `InProcessLink` does, having no socket to lose.
  `LINK_REPORT_METHODS["report_event"]` names it now.

- **`report` carries `seq`, and two frames are new.** `resume` names the runs
  a reconnecting provider is still holding; `resumed` answers with the last
  `seq` funduq accepted for each of them, plus the ones it is not holding any
  more. The provider replays from the watermark and stops producing for the
  rest. The sequence is the *provider's* own count for that run, from 1 — not
  funduq's, which numbers everything on a run including its own events, so the
  two could never be the same number.

- **`ProviderRuntime` buffers instead of dropping.** An event produced while
  no link was attached used to be taken off the queue and discarded, which
  made resume unreachable no matter what the wire carried: a reconnecting
  provider would have resumed a stream with a hole in it.
  `max_buffered_events` (default 1024) bounds it, and **a gap wider than the
  buffer abandons the run rather than resuming it with a hole** — funduq's
  grace then runs out and it records the `provider_left_holding_it` it
  actually observed.

- **Both machines can outlive their connection.** `reopen()` puts a session in
  front of a new one, keeping what it is the authority on: how much of each
  run funduq has actually seen. That state could never have lived in a link
  object, because a link object is what gets thrown away on every blip.

*For an implementation in any other language*: `report` gains an optional
`seq`, and `resume`/`resumed` are new. Ignore all three and you behave exactly
as before — a link that sends no `seq` is given a watermark of zero and simply
never resumes.

---

## Revision 9 — 2026-08-27

**The completion half gets the same treatment**, and the shared opening is
shared rather than restated.

- **`funduq_provider_sdk.llm.protocol`** carries `FunduqLlmSide` and
  `ProviderLlmSide`. Both kinds of work are answered with a *stream* — a
  run's answer is its events and then its finish — so that is not what
  separates them. Two things do. **A run is admitted first**: an offer is
  answered three ways before any output exists and the next utterance of that
  conversation waits until the run is claimed, while a completion is assumed
  taken and can only fail afterwards, so this half has no three-valued ack and
  no delivery deadline. And **a run outlives any one offer of it**, which is
  why its output is addressed by `runId` while a completion's chunks are
  addressed by the request's own id. A completion is open until exactly one of
  `completion.end`, `completion.failed` or a lost link.

- **`abandon` is new, and it closes a hole that had no name.** When a KYOK
  caller stops consuming, an in-process handler hears `GeneratorExit`; over a
  wire nothing reached the provider at all, so it went on generating into a
  consumer that had gone. A driver sends `abandon` when its stream closes.
  Core needs no new verb for it — `ConnectedLLMProvider` has none to add.

- **Two frames revision 8 shipped as loose dicts are now typed**, and both
  are breaks against revision 8. They were the same mistake the machines
  exist to remove, made one level down: a shape whose field names were
  already published — `REGISTRATION_FIELDS`, `LINK_QUERY_METHODS` — with
  nothing checking them.

    - `register.agents` is a list of **`Registration`** (`name`,
      `description`, `agentCardExtra`, `metadata`) with `extra="forbid"`.
      A misspelt key used to travel intact and be dropped in silence by core,
      whose reader cannot tell a missing field from a typo
      (`agent.get("description", "")`). `REGISTRATION_FIELDS` is now read off
      the model rather than typed out beside it. *`AgentHandle.as_registration()`
      still returns a dict and still works — it is validated on the way into
      the frame.*
    - `query` is gone; the one query it carried is its own frame,
      **`query.thread_messages`** with `threadId` and `limit`. A `method`
      string and a bag of `args` meant a transport writing `args["thread_id"]`
      by hand, which is how a field name goes wrong silently. A second query
      kind is a second frame, and adding one moves this fingerprint — which is
      the right price.

- **Registration is per link kind, not shared.** `register.llm` carries
  `names` and one `metadata` document; the agent link's `register` carries
  agent records. They looked like one frame until the LLM roster's metadata
  had nowhere to travel. *If you built against revision 8's `register` for an
  LLM link, send `register.llm` instead* — nothing else about it moved.

- **The handshake is now stated once** for both link kinds, in
  `FunduqLinkMachine` and `ProviderLinkMachine`. Nothing about it changed;
  what changed is that a fix to it can no longer land in one copy and not the
  other. Deleting and querying stay shared too, because those shapes really
  are the same.

*For an implementation in any other language*: the agent link is untouched.
The LLM link's frames above are new surface, and `register.llm` is the one to
notice if you had assumed the two links published their rosters the same way.

---

## Revision 8 — 2026-08-27

**The link's state machine ships as code**, in `funduq_provider_sdk.protocol`.
Nothing already on the wire changed shape; what is new is that the orderings
around it are no longer only prose.

- **A published frame vocabulary.** Four classes — handshake (`Connect`,
  `ConnectOk`, `ConnectErr`), request carrying an `id` (`Offer`, `Query`,
  `Register`, `Delete`), reply carrying the request's `id` (`Ok`, `Err`), and
  notify carrying none (`Report`, `Finish`, `Cancel`). Every frame is a
  pydantic model with camelCase aliases, so the mapping is written once rather
  than once per transport, and `Offer.run` nests the delivered-run envelope
  unchanged.

- **`Connect` carries `maxConcurrentRuns`.** It had nowhere to travel before:
  core needs the figure to schedule against, in-process read it off the
  runtime, and the vocabulary had no field for it. Declared at the open rather
  than with a registration, because it is a property of the party on the other
  end and not of any agent it publishes.

- **Two sans-io machines**, `FunduqSide` and `ProviderSide`: frames in, frames
  and events out, no I/O and no clock — time enters as `now` and leaves as
  `next_deadline()`. What each one refuses is now a transition rather than a
  paragraph: a first frame that is not `Connect`, a second `Connect` on an
  open link, a second answer to one offer, an answer to an offer never made.

- **The dump rule, stated once because it is two rules.** A frame is dumped
  `by_alias=True` **without** `exclude_none`, and a typed AG-UI event is
  dumped with it. Both halves are load-bearing and they pull opposite ways:
  `RunAgentInput` has required fields that are legitimately `null` — `state`,
  `forwardedProps` — so stripping nulls from a frame produces a `runInput` the
  far side cannot rebuild, and a perfectly good run comes back as a permanent
  refusal; while leaving them in an event injects `timestamp: null` and
  `rawEvent: null` into a caller's stream. They lived in different paragraphs
  of `writing-a-transport.md` and never met until one function had to do both.

- **An offer is legal before a registration has been answered**, on both
  sides. Neither machine holds a registration state, which is not an
  allowance but an absence: core's roster goes live and nudges the broker
  before `register_agents` does its write and commit, which on Postgres is a
  network round trip.

*For an implementation in any other language*: nothing you already send or
parse has changed, and no vector moved. The frames above are new surface you
may adopt or ignore — the machines are a Python convenience, and the wire they
speak is now written down. If you do adopt them, the two dump rules are the
part to copy exactly.

*For a Python transport*: `FunduqLink` is unchanged and still supported. It
remains the right surface for provider authors; a transport can now mount
`ProviderSide` instead of subclassing it.

---

## Revision 7 — 2026-08-26

**The types reach the signatures**, and the surface reaches the Python API
that had been breaking outside it.

- **`dispatch_hop` takes a `DispatchTarget`.** It used to take
  `provider_key` and `agent_name` — two adjacent, same-typed, interchangeable
  strings. Handing them over backwards signed happily and verified happily;
  what broke was the *honest* provider extending the chain, refused with a
  message naming the innocent successor. `DispatchTarget` already existed and
  stopped six lines short of the function people call. *Change
  `dispatch_hop(key, chain, provider_key, name)` to
  `dispatch_hop(key, chain, DispatchTarget(provider_key=…, name=…))`.*

- **`verify_chain` hands back the hops it parsed.** `ChainResult.hops` is a
  list of `Hop`, each with `actor_public_key`, `prev_hash` and a typed
  `dispatched_to`; `actor_public_keys` is now derived from it and every
  existing use of it, `head` and `presenter` is unchanged. This is what makes
  the check `mechanisms/actor-chain.md` describes — pin funduq's key, require
  a hop of funduq's on the path — writable without decoding a JWT by hand.
  Ten call sites in this repository were doing exactly that, which is not an
  inconvenience: it is the posture that produced the revision 6 bug.

- **`Hop.is_witness` is gone**, one revision after arriving. It was never
  used, and its own docstring warned against the reading it invites. Whether
  a hop is a witness's is decided by `actor_public_key` — a key the reader
  pinned — so the honest predicate reads two fields, and a lone bool answers
  the question that must never be asked alone. *Write
  `hop.dispatched_to is not None and hop.actor_public_key == pinned_key`.*

- **A witness appears in a chain only as a witness.** Revision 6 allowed the
  hop after a dispatch to be signed by the dispatching key, for a witness
  re-offering work nobody took — and re-offering is another dispatch, but the
  code accepted any hop that key signed, including a plain one. Nothing
  outside funduq can reach that (it needs funduq's key), so this closes no
  hole; it moves the code's edge back to where the sentence always said it
  was. **A chain your implementation used to accept may now be refused**: a
  plain hop signed by the key that dispatched immediately before it.

- **`funduq_contract`'s exported signatures are in the surface now.** They
  were not, which is why the break below shipped described as no break at
  all. Wire compatibility is not the whole of the contract when one of the
  four distributions *is* the contract.

> **Revision 6 broke Python callers and said it did not.** Its entry reads
> "chains you were building are unaffected", which is true of every byte on
> the wire and false of anyone's code: `sign_hop`'s third parameter went from
> `dict[str, str] | None` to `DispatchTarget | None` in 0.0.3, so a call
> written against 0.0.2 raises `AttributeError: 'dict' object has no
> attribute 'provider_key'` from inside a function the caller never wrote.
> Corrected here rather than edited into that entry, and the surface widened
> above so the next one fails a test instead of a stranger.

*For an implementation in any other language*: one rule changed — a plain hop
signed by the key that dispatched before it is now refused. The vectors are
otherwise untouched, and every other item above is Python only.

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
