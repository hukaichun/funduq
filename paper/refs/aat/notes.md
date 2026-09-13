# Attenuating Authorization Tokens (AATs)

- **id** — `draft-niyikiza-oauth-attenuating-agent-tokens-01`
- **who** — N. A. Niyikiza, Tenuo (single author)
- **when** — 2026-06-15, expires 2026-12-17. Individual submission, not adopted
- **where** — https://datatracker.ietf.org/doc/draft-niyikiza-oauth-attenuating-agent-tokens/
- **status** — `summary` — quotes below are **not safe to ship**
- **read on** — 2026-08-25 (fetch summary only)

## What it is

A signed credential format for task-scoped delegation: `par_hash` binds each
token to its parent's exact signing input, the holder is identified by
`cnf.jwk` with no `sub`, capabilities live in `authorization_details` and
must narrow monotonically, and verification is fully offline against a
**configured root trust anchor**.

## Quotes we use

> a signed credential format for task-scoped delegation in AI agent systems

> Without such attenuation, a token broad enough to support a multi-step
> workflow can carry more authority than an intermediate agent needs for its
> current step.

**Where** — §2.2 (as one of the four incompatible vocabularies). **Why** —
capability attenuation as the answer, which needs the vocabulary to attenuate
*in*.

Out of scope by its own text, per the summary: **revocation** ("Token
revocation is outside the scope") and **transport binding**.

## Cautions

- **Not read verbatim.** Match every string above before shipping.
- Its trust anchor is *configured per deployment*, not a global authority.
  The accurate framing for §2.1 is a **pre-agreed trust root**, which covers
  this and HDP; "central issuer" alone overclaims against both.
- It defines no mechanism for a hop declining to extend — record that as
  "defines none", never "forbids".
