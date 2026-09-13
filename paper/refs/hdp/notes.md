# HDP — Human Delegation Provenance

- **id** — arXiv:2604.04522; also `draft-helixar-hdp-agentic-delegation-00`
- **who** — Asiri Dalugoda, Helixar Limited, Auckland, New Zealand (single author)
- **when** — March 2026 (PDF metadata says created 2026-03-30)
- **where** — https://arxiv.org/abs/2604.04522
- **status** — `verbatim` (PDF text extracted with `pdftotext -layout`, quotes matched)
- **read on** — 2026-08-25

## What it is

A JSON token binding a human authorization event to a session, accumulating a
signed hop per agent in an append-only chain, verifiable offline from the
issuer's Ed25519 key and the session id. **The closest published thing to
this paper's mechanism**, and it says one of this paper's own sentences —
which is why the difference has to be drawn precisely.

Token shape: `{hdp, header, principal, scope, chain, signature}`. The header
carries `token_id`, `issued_at`, `expires_at` (24h default), `session_id`.
Scope carries a free-text `intent`, `authorized_tools`, `data_classification`,
`network_egress`, `persistence`, `max_hops`.

## Quotes we use

> Semantic validation of agent actions against declared scope is an
> application-layer concern; **HDP provides the record, not the enforcement.**
> (§4.2.3)

**Where** — §2.2. **Why** — record-not-enforce is **not ours alone**. The
line has to be drawn on *what is recorded*: HDP records scope and defers the
check; this paper records no scope at all. A reviewer who knows HDP will say
"already said" unless the draft draws it there.

> HDP v0.1 uses the issuer's key for all hop signatures, meaning agents do not
> sign with their own keys. This simplifies key management but means hop
> signatures attest that **a hop was recorded at the issuer**, not that the
> specific agent produced it. (§7.1)

**Where** — §2.1. **Why** — its chain proves central recording, not per-party
signing. Its own limitations section, so it needs no interpretation from us.
Per-agent keys are a stated v0.2 plan.

> HDP records what the human authorized but does not enforce it. (§7.2)

**Where** — §2.2, alongside the §4.2.3 line.

## Cautions

- **Do not call it centralised without qualification.** Its design principle
  2 is self-sovereignty: "any organization can issue and verify HDP tokens
  **without registering with a central authority or anchoring to a
  third-party key**". Its centrality is per-deployment, not global. The
  accurate claim is about a **pre-agreed trust root**, which covers both.
- Its replay defence is expiry plus session binding, with **no possession
  check** — relevant to §7.2.1 but state it as *what it does*, not as a
  criticism it fails to make of itself.
- Its §5.4 concedes the semantic boundary itself: a legitimate agent
  recording a genuine hop with a misleading `action_summary` "is not
  detectable by the protocol alone".
