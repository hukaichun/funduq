# OAuth Identity and Authorization Chaining Across Domains

- **id** — `draft-ietf-oauth-identity-chaining-17`
- **who** — OAuth WG
- **when** — updated 2026-07-19, submitted to IESG for publication, expires 2027-01-20
- **where** — https://datatracker.ietf.org/doc/draft-ietf-oauth-identity-chaining/
- **status** — `summary` — **not safe to ship, and the reason matters**
- **read on** — 2026-08-25 (fetch summary only)

## What it is

The mature one. RFC 8693 token exchange plus RFC 7523 JWT grant, composed so
identity and authorization context survive a trust-domain boundary: exchange
at home, present the grant abroad, receive an access token. **Working-group
adopted and at the IESG** — everything else in §2 is an individual
submission.

## Quotes we use

The draft's §2.4 says it does token exchange, not responsibility. **No
verbatim quote supports that yet**, and this is the source where the
distinction bites hardest:

- "the specification does not mention audit or accountability" — a
  **silence**;
- "the specification states audit and accountability are out of scope" — an
  **exclusion**.

The fetch summary asserted the second. **It has not been verified**, and the
pre-submission checklist forbids one standing in for the other.

## Cautions

- **Read the document and settle which of the two it is** before §2.4 ships.
  If it is a silence, the sentence must say so — a silence is still evidence
  that the mature standards track leaves the question open, and it does not
  need to be dressed up as more.
- Its status will move. It is at the IESG; it may be an RFC by submission.
