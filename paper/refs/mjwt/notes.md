# Mandate JWT (MJWT)

- **id** — `draft-sato-soos-mjwt-00`
- **who** — Tom Sato, MyAuberge K.K. (single author)
- **when** — 2026-05-24. Individual submission, not adopted
- **where** — https://datatracker.ietf.org/doc/html/draft-sato-soos-mjwt-00
- **status** — `summary` — **not safe to ship**
- **read on** — 2026-08-25 (fetch summary only)

## What it is

A WIMSE workload credential profile granting an agent authority to perform a
named set of **Cedar actions** on a Sovereign Object instance under a named
human principal. Adopts a `delegation_chain` claim; each record carries
issuer, recipient, mandate id, timestamp and a GEC signature.

## Quotes we use

Used in §2.2 only as one of the four vocabularies — `cedar_actions` written
directly into the credential. **No verbatim quote is currently relied on**,
which is the only reason its `summary` status is not blocking.

## Cautions

- **Not read verbatim.** If any sentence of it enters the draft, read it
  first.
- Check where its `delegation_chain` claim is actually defined — the summary
  attributes it to a "McGuinness Actor Profile", which has not been located.
  **Do not repeat that attribution without finding the source.**
- Its `human_principal_id` stays constant along the chain, which is close to
  this paper's segment head and worth a sentence of differentiation if it
  ends up in §2.
