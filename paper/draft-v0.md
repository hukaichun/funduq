# Draft v0 — AAMAS 2027 main track (EMAS subject area)

> **Status: first draft, structure complete, prose written where the argument
> is settled and marked `[STUB]` where it is not.** Written 2026-08-25 from
> the design statement given in conversation that day, plus
> `strengths-and-gaps.md`, `downstream-review-2026-08.md` and
> `retractions.md`. Nothing here is committed prose; the point is to see the
> shape early enough to be wrong cheaply.
>
> **Constraints** (from the AAMAS 2027 instructions, read 2026-08-25):
> eight pages excluding references, LaTeX mandatory, **double-blind**,
> supplementary ≤25MB and reviewers need not read it — *anything essential
> must be in the paper*. Abstract 2026-10-01, paper 2026-10-08; OpenReview
> accounts two weeks before the abstract, so **by ~2026-09-17**.
>
> **Double-blind handling.** The system, the repository and the probes are
> the evidence and all three are identifying. Throughout this draft the
> system is called **the broker**; before submission every occurrence of the
> project name, the repository URL and the author's handle must be gone, and
> the artifact link becomes an anonymised mirror. The probes are quoted by
> *what they do*, never by repository path.

---

## Title candidates

1. **Responsibility Chains: A Broker That Records Delegation Without Governing It**
2. Every Node Is a Supplier: Delegation Boundaries for Agents That Represent Businesses
3. What a Chain Proves: Origin, Possession, and the Limits of Delegation Provenance

> (1) says the position and the refusal in one line and is the safest for a
> reviewer skimming titles. (3) is the most honest about the paper's
> strongest evidence but reads as a negative result. Decide late.

---

## Abstract `[STUB — write last]`

Must contain, in this order: an agent represents a business rather than a
person; delegation makes every provider a caller, so the two roles are
recursive; systems that answer *what may this agent do* build one scenario
into the protocol and make the others inexpressible; a broker that records
responsibility without adjudicating it keeps both parties' positions intact;
and two properties of signed delegation chains that we falsified against a
running implementation.

---

## 1. Introduction

**¶1 — an agent is not a person.** We speak of agents as though they were
people, and then decline to treat them as such: no agent is educated, holds
rights, or votes. What an agent is, always, is the encapsulation of a
business — a unit of work someone offers and someone else consumes. The
question of an agent's *own* standing therefore never arises. Every question
that matters is about the two parties on either side of it.

**¶2 — the two things a protocol must not take away.** A provider publishes
a capability and must keep the freedom to implement it as it sees fit,
including the freedom to subcontract without disclosing to whom. A caller
pays for the work and must keep the standing to intervene in it, to see what
it needs to see, and to find someone accountable when it goes wrong. Neither
is negotiable, and a mechanism that preserves one by spending the other has
solved nothing.

**¶3 — the recursion that makes this hard.** The moment a provider delegates,
it becomes a caller. The same party must simultaneously be protected in its
freedom to implement and held to its answerability upstream. There is no
fixed assignment of roles to parties that a protocol can encode, because the
roles alternate along every path of the delegation tree.

**¶4 — why a policy cannot do it, and a boundary can.** A policy has to
decide which party is which before it can act, and that decision is an
adjudication: it takes a side between two parties who both have a legitimate
interest. A boundary does not. It records where responsibility ends and
begins, and leaves the exercise of rights to the parties who hold them. Not
adjudicating is not modesty; it is the only position from which both can be
preserved.

**¶5 — what the field does instead.** Every deployed and proposed system in
this space answers a different question — *what may this agent do* — and
each answers it by building one application scenario into the protocol
itself. §2 shows five, and what each one makes inexpressible. The cost is
not that they are wrong; each is right for its scenario. The cost is that
adopting one removes scenarios from the space.

**¶6 — contributions.**
1. A statement of the delegation problem in which roles are recursive and
   the intermediary is a recorder rather than an adjudicator (§3).
2. A mechanism — responsibility chains — in which what crosses a boundary is
   keys and structure, never permissions, and in which extending or not
   extending is itself the declaration (§4).
3. A demonstration that a *right* can ride that structure without the
   intermediary defining the right: an authorization chain layered on a
   responsibility chain, boundary-truncated (§5).
4. **Two properties we falsified against the running system** (§6): a signed
   chain proves origin and not possession, and a chain's completeness is not
   provable. Both are demonstrated by executable probes, and one of the two
   remains open.

> `[STUB]` ¶5 needs the *hook*: the reader must feel a live problem in the
> first column. Candidate, sourced rather than asserted: of surveyed
> organisations, 28% can trace an agent's actions to a human sponsor and
> 24.4% have visibility into agent-to-agent communication. Verify the
> survey's n and methodology before it goes in — `retractions.md` §E, any
> percentage carries its n or is cut.

---

## 2. What the neighbours make inexpressible

> The related-work section, and the paper's most reusable table. Its rule,
> from `retractions.md`: **every "they do not do X" is sourced from their own
> text, preferably their own limitations.** No claim survives here that we
> have not read in full.

| System | What *authorization* means | Whom the agent belongs to | Made inexpressible |
|---|---|---|---|
| Gateway/proxy layer with OAuth on-behalf-of | scopes in a token an authorization server issued; the agent inherits a human's access | a human user | the agent as an *independent business* serving many callers; a delegate that is itself accountable rather than a name in an `act` claim |
| Agent-as-principal | the agent has its own identity inside one tenant's directory | the tenant that registered it | a provider with no directory of its own, or one crossing organisations without federation |
| Verifiable-credential delegation (scoped, revocable, rooted at a responsible party) | a permission set written into a credential | the responsible party at the root | any deployment where the two sides share no permission vocabulary — see below |
| Attenuating capability tokens | a capability that may only shrink at each hop | whoever originated the chain | *break*: a subtree becoming the provider's own implementation detail |
| Adjudicated clearing | an obligation object cleared by a decision on evidence | the co-signers of the obligation | the case where both parties have a legitimate interest and no one has standing to decide |

**The common shape.** Answering *what may this agent do* forces one of three
prerequisites: a central issuer (excluding independent providers), a shared
permission vocabulary (excluding everyone who lacks one), or an adjudicator
(excluding disputes with two legitimate sides).

**The second prerequisite does not currently exist.** `[STUB — verify]` Of
active agent-authorization Internet-Drafts, a small minority carry
permissions in a structured authorization-details field and the large
majority do not reference that mechanism at all; two open specifications for
the same layer, sharing an acronym, shipped within a week of each other with
incompatible verdict vocabularies. **Before this ships: obtain the draft
counts from the IETF datatracker directly rather than from a secondary
source, and state the query and date.**

**And it cannot exist in the usual form**, because an agent selects its tools
at inference time from a prompt and prior outputs — the set is not
enumerable when a credential is issued. `[STUB]` Attribute this to a primary
source, not a blog.

> **Not in the table, deliberately**: the classical line this work descends
> from — contract-net task allocation, agent communication languages,
> electronic institutions — belongs in §3, as ancestry rather than
> competition. `classical-mas-line.md` records that seven recent
> agent-protocol papers cite none of it, which is itself worth one sentence.

---

## 3. The setting

**3.1 Businesses, not persons.** A delegation tree is rooted in a business
need and every node is a supplier of a business. Whether a human sits at the
root is not a separate question: a unit that answers for nothing is not a
business, and a business is made of people who answer for things. This
dissolves rather than solves a problem posed elsewhere in the literature —
that a subdelegation chain leaves fault unassigned *because there is no
human principal to absorb it*. If nothing absorbs it, there is no business,
and nothing to clear.

**3.2 What the intermediary is for.** `[STUB]` The broker holds the run,
records who asked and through whose hands the work passed, and hands the work
to whoever is serving. It implements no transport and speaks no protocol of
its own; the interaction vocabulary is the standards'.

**3.3 The discipline: no interaction mode per scenario.** `[STUB]` Whatever
the broker invents must be opt-in and must leave a standard client's
behaviour unchanged — a property that can be tested rather than asserted.
State the test.

---

## 4. Responsibility chains

`[STUB — the mechanism section; longest, and the one EMAS reviewers will
read hardest.]`

Must cover, in this order:

1. **The chain carries keys and nothing else.** No subject, no time, no
   scope. Each hop is signed by the key it names and hash-links to the
   previous hop.
2. **Extending is the declaration; silence is the break.** There is no
   per-edge flag. What extension buys — escalation path, answering rights,
   visibility — is exactly what a break refuses, so a flag would have
   nothing to mean. Segment boundaries are *derived from where signatures
   reached*, never registered.
3. **The bundle.** Intervention rights, cost attribution and visibility
   follow the same boundary, and that is what makes the declaration
   incorruptible: *the caller pays but may not look* and *the provider looks
   but does not pay* are both structurally unsayable. Note: the bundle is a
   property of the declaration's semantics, not of any one implementation
   of cost.
4. **The intermediary decides nothing about the declaration**, and does not
   determine what any party *is*. The vocabulary of agency and resource
   ownership names the two stable shapes a free, priced declaration collapses
   into; it is not a test anyone applies.

---

## 5. An authorization chain on top

A responsibility chain says who answers. It says nothing about what anyone
may do — and a right can nonetheless travel along it, without the
intermediary defining the right.

**The rule.** A right held by a segment's head may be exercised by any party
inside that segment, and stops at the boundary.

**The worked instance.** `[STUB]` A caller's own model credential, usable by
the agent serving that caller's run and by anything the segment extends to,
truncated where the segment ends: a broken-off subtree funds itself. The
intermediary never judges what the credential may be spent on. It decides
only where the segment ends.

**Why this is the answer to §2.** The systems in that table define rights
*inside* the chain, and therefore need a vocabulary everyone agrees on. Here
the chain defines only structure and the right attaches to it, so no prior
agreement about the meaning of permissions is required.

> **Honesty, in the paper**: this instance is experimental. It is complete as
> a demonstration that layering works and is not offered as a production
> mechanism. `[decide]` whether it appears as a section, a paragraph in §4,
> or future work.

---

## 6. What we falsified

> The paper's most distinguishing section, and the reason to write it at all:
> in a literature where mechanism properties are asserted in prose, these were
> executed. Both probes were written red, before the fixes, and one is still
> red.

**6.1 A signed chain proves origin, not possession.** A chain proves the
head's key signed the first hop. It does not prove that whoever presents it
now holds that key — and the chain is not a secret, since the broker relays
it to the serving provider verbatim so the agent may verify it rather than
trust a summary. A probe has the provider present the caller's own chain back
at a door for work the caller never requested: it is accepted, recorded under
the caller's head, and the two records are identical in every field carrying
authority.

*The fix, and its shape*: the broker cannot authenticate a presenter, because
a door receives bytes rather than a connection. The seat in front of it can,
and passes in the key it authenticated; the broker compares that key against
the chain's **last hop** — never its head, which is exactly the mistake that
lets the replay through. Authentication stays outside; the comparison belongs
inside, where it is tested once instead of reimplemented per deployment.

**6.2 Completeness is not provable.** Signatures and hash-links prove nobody
was inserted, reordered, or spliced in from another chain. They never prove
nobody was *removed*. A probe rebuilds `caller → A → B` as `caller → B` from
the first hop's own token: nothing is forged, it verifies, and the head is
unchanged. Two properties do resist and are asserted alongside it — the head
cannot be dropped, and a hop from a foreign chain cannot be grafted on.

*What reaches it*: the broker signing each dispatch with the agent it
dispatched to. An agent is addressed as a (provider key, name) pair, and that
provider key is the one that signs the next hop when the provider extends
honestly — so a hop and its successor check against each other, and a branch
cannot satisfy both.

**6.3 What we do not claim.** A recent survey states that no deployed
protocol can cryptographically prove which human principal authorized which
specific agent to perform which *specific action* at the third or fourth hop.
**This work does not satisfy that either**: binding the first hop to the act
it authorizes is deliberately deferred, so a party that extends honestly and
then acts under the caller's head is visible and attributable but not
prevented. We claim the position and the path, never that sentence.

Nor do we claim that recording without adjudicating is *effective*. No one
has measured that, ourselves included; the adjacent result that appears to
support it comes from a design that also mediates completely and does
adjudicate, and therefore contains no record-only arm to compare against.

---

## 7. Implementation `[STUB]`

Short. The mechanism is implemented and under test; the one designed-but-
unimplemented part is the disclosure that translates a key to a person, which
belongs to a deployment's own identity provider and is named as such. State
the implemented-versus-designed split as a table and let it be small.

**Do not** claim the mechanism is unimplemented — an internal table said so
while tests exercised it, and that error is recorded in `retractions.md` as
its own failure mode: trusting a document that had fallen behind the code.

---

## 8. Discussion and limitations

- **What this work removes from the space.** Every design forecloses
  something; §2's table is only fair if we say what ours forecloses. Ours has
  no vocabulary for a *standing intent* — a monitor or resident guard is
  modelled as many runs plus a thread, and the standing-ness lives outside
  the record. Responsibility for a timer-driven run traces to a deployment
  decision rather than to a moment of human choice, and nothing on the chain
  points at that decision.
- **Governance attaches here; it is not provided here.** Two independent
  papers state the demand: governance is a missing architectural layer that
  must compose with existing interoperability standards, and the governance
  questions around clearing are explicitly unsettled. `[quote both]`
- `[STUB]` Federation, and why chains crossing several brokers need no extra
  design.

---

## 9. Related work — placement notes `[STUB]`

Merge into §2 or keep separate depending on space. The classical line
(contract net → agent communication languages → electronic institutions →
the accountability line in this venue's own journal) is the handshake with
the likely reviewer, and `classical-mas-line.md` has it with citations.

---

## Open decisions before writing prose

1. **Title** — decide late, after the abstract exists.
2. **§5's placement** — section, paragraph, or future work.
3. **The §1 hook** — which sourced number, with its n verified.
4. **Anonymisation plan** — anonymised artifact mirror, and whether the
   probes ship as supplementary (reviewers need not read it, so anything
   load-bearing must be described in §6 itself).

## Checks before submission

- Every percentage carries its n, or is cut.
- Every "they do not do X" cites their text, ideally their limitations.
- Every claim about what this system implements cites code or a test, never
  a page of documentation.
- Re-sweep the venue's recent listings the week of submission.
