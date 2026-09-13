# Delegation Chain for OAuth 2.0

- **id** — `draft-liu-oauth-chain-delegation-00`
- **who** — D. Liu (Alibaba), H. Zhu (Alibaba), S. Krishnan (Cisco), A. Parecki (Okta)
- **when** — 2026-06-06, expires 2026-12-08. Individual submission to the OAuth WG, **not adopted**
- **where** — https://www.ietf.org/archive/id/draft-liu-oauth-chain-delegation-00.html
- **status** — `verbatim` (HTML fetched, tags stripped, every quote below matched against the document text)
- **read on** — 2026-08-25

## What it is

A JWT claim, `delegation_chain`, companion to RFC 8693's `act`: an ordered
array of delegation records, one per hop, each carrying delegator and
delegatee URIs, a timestamp, optionally a scope and a machine-enforceable
policy, and signatures. The nearest rival to this paper's mechanism, and the
one to watch — if the OAuth WG adopts it, `funduq-contract` goes from
complement to competitor.

## Quotes we use

> Each delegation hop must **preserve the original user's authorization
> intent** while **constraining what each downstream agent is permitted to
> do**.

**Where** — §1, §2 opening. **Why** — the field's framing in one sentence:
delegation as authorization carried forward.

> The `act` claim is **constructed unilaterally by the Authorization
> Server**. The delegating agent leaves **no independent cryptographic
> evidence** that it authorized a specific delegation. This limits
> non-repudiation and post-hoc audit capabilities.

**Where** — §2.4. **Why** — **the strongest paragraph in the section.** They
name this paper's mechanism as their own second gap. Pair it with the
requirement levels: `as_signature` is **REQUIRED**, `delegator_signature` is
**RECOMMENDED**. They found the same hole and made it a MAY.

> For opaque (non-JWT) access tokens, the Resource Server **MUST** use token
> introspection ([RFC7662]) to retrieve **the authoritative
> `delegation_chain` from the AS**, rather than trusting any client-supplied
> chain data.

**Where** — §2.1. **Why** — the central-issuer support, in their words: the
chain's authority lives at the AS, not in the chain.

> **This field is typically absent.** The delegation is governed solely by
> the OAuth `scope` parameter, and the Resource Server applies scope-based
> authorization. When this field is absent, the Resource Server MUST apply
> scope-based authorization only.

> …a Rego policy structure…, ALFA (Attribute-based Logical Framework for
> Authorization), XACML, or **any other policy representation agreed upon by
> the delegator and the Authorization Server**.

> For expressive policy languages where automated subset checking is
> computationally expensive or **undecidable**, the RS **MAY rely on the AS's
> attestation** (`as_signature`) as evidence that the AS already performed
> policy narrowing validation at issuance time.

**Where** — §1 and §2.2 (the two overlap; **one of them has to give**, see
the draft's open decision). **Why** — the shared-vocabulary support given up
in three steps by its own proposers: shared vocabulary → bilateral agreement
→ trust in the centre. This paper does not have to argue the point.

> This version of the specification focuses on **linear** delegation chains;
> other complex topologies such as diamond-shaped delegation, where multiple
> paths converge on the same agent, may be addressed by future extensions.

> A RECOMMENDED default maximum depth is **5 hops**.

**Where** — §2.4. **Why** — self-stated bounds. Note also what is absent
without being excluded: **no mechanism expresses a hop declining to extend.**
Say "the specification defines none", never "the specification forbids it".

## Cautions

- The record's `delegator_signature` exists and is RECOMMENDED — do not write
  that they left the delegating party unable to sign. The claim is about
  which signature is **required**.
- Adoption status will move. Re-check before submission; if the WG adopts it,
  §2's framing changes.
