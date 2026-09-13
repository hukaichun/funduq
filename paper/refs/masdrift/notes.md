# MasDrift

- **id** — arXiv:2608.07556v1
- **when** — 2026-08-18
- **where** — https://arxiv.org/abs/2608.07556
- **status** — `verbatim` (full text read 2026-08-21, quotes recorded then)
- **read on** — 2026-08-21

## What it is

A measurement paper on authorization drift across handoffs in multi-agent
systems, with a deliberately benign threat model so every failure is
endogenous to decomposition. **The strongest empirical ally in the draft.**

## Quotes we use

> delegators cannot anticipate downstream needs

**Where** — §1 ¶3. **Why** — the structural reason a pre-written constraint
can only be a guess, from a paper that measured the cost of guessing.

The measured cost, used in §1 ¶3: entrusting the policy to the same handoffs
that lose the constraint blocks up to **54.5%** of required calls and costs
up to **36.3** completion points, against at most 3.5% for the arm that lives
outside the coordination graph.

**Where** — §1 ¶5. **Why** — 92% of one lead's constraint losses land at the
**first** handoff: the deferred call loses its addressee immediately, not
gradually.

Other lines worth the space if §8 needs them:

> Near-zero violations do not imply preserved authorization

> The problem is not that users are insufficiently explicit — explicitness
> does not survive a handoff

## Cautions

- Its Source arm works by living **outside** the coordination graph, which is
  this paper's architectural position — but Source also **adjudicates** and
  assumes complete mediation, and MasDrift has **no record-only arm**. It
  does not test rule zero. Never claim it vindicates it.
- Confirmations auto-approved in the main runs; single LLM judge for two
  metrics; synthetic English-only environments.
