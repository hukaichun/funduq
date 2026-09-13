# Auditable Agents

- **id** — arXiv:2604.05485v2
- **who** — Yi Nian et al., USC / Arizona State / Johns Hopkins
- **when** — v2, 2026-08-13
- **where** — https://arxiv.org/html/2604.05485
- **status** — `summary` — **the §1 hook rests on this and the quotes are not yet safe to ship**
- **read on** — 2026-08-25 (fetch summary only)

## What it is

A position paper defining auditability as five dimensions — action
recoverability, lifecycle coverage, policy checkability, **responsibility
attribution**, evidence integrity — and three mechanism classes (detect,
enforce, recover), with six open problems.

## Quotes we use

> full delegation chains recoverable from immediate executor to originating
> principal

**Where** — §1 ¶1. **Why** — their definition of responsibility attribution,
which is this paper's subject in someone else's words.

> no existing work covers all five dimensions jointly

> **OP3** — Capturing full responsibility chains across multi-agent delegation

**Where** — §1 ¶1, and §3's correction that the *concept* is not what is
missing. **Why** — three institutions, published two weeks before the draft,
naming this paper's subject as unsolved. It replaced two survey percentages
whose n was never verified.

Also relevant, not yet used: **OP6**, cross-party audit aggregation when
several organisations hold partial traces.

## Cautions

- **Every quote above came from a fetch summary.** Read the paper and match
  each string before it ships. This is the single most load-bearing citation
  in the draft — the introduction opens on it.
- Caveats it states about itself, which should be acknowledged rather than
  discovered by a reviewer: evidence comes from the authors' own tools
  (agent-audit, Aegis, IET), no end-to-end audit on a deployed system,
  open-source projects only, six projects and 48 attacks.
- It is a **position paper with a survey**, not a mechanism. Cite it for the
  gap, never as a rival design.
