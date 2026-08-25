# funduq-contract

Part of [the SDKs](../sdks.md).

The bytes both sides of funduq sign and verify, written once: the signing
payloads, the actor-chain hop format, and signature checking. Core depends on
it and so does the provider SDK; neither depends on the other.

```
pip install funduq-contract
```

## What is in it

- **`payloads`** — one function per act, each returning the canonical byte
  string a signer signs. Pure, and taking no key.
- **`chain`** — the hop format: `sign_hop`, `new_chain`, `extend_chain`,
  `dispatch_hop`, and `verify_chain` with its `ChainResult` (whose `head` and
  `presenter` are the two ends a caller-side check compares).
- **`signatures`** — `verify_signature`, `new_nonce`, and the provider
  fingerprint helpers.

**No private key is held here.** Producing the bytes and having custody are
different jobs, which is what lets one package sit under core and an SDK at
once without either lending the other its keys —
`funduq.identity.FunduqIdentity` and
`funduq_provider_sdk.ProviderIdentity` keep theirs.

Nothing here talks to a network or a database, and the dependency list is two
entries: `cryptography` and `pyjwt`.

## Why it exists

Core and the provider SDK each used to carry a copy of all of this, under two
sets of names — `resolve_signing_payload` on one side, `resolve_payload` on
the other. The split had a real justification and half of it survives: the
SDK must not depend on *core*, because nobody should install sqlalchemy,
alembic and a database driver to sign a hop.

But that argues against depending on core, not for writing the format twice.
The second copy was defended as a second opinion, and there was a recorded
win to point at — the duplication once caught a payload change 219 green
tests had missed. That win happened six hours before
[`contract-vectors.json`](../contract-vectors.json) existed. The vectors were
the durable answer to it, and a frozen byte string catches a wrong change to
one shared implementation exactly as well as it catches two copies drifting.

## The vectors are recorded, never derived

The vectors are the authority for an implementation in any language, and they
work because they are **old**: literal bytes and signatures, written down and
left alone. A file regenerated from the code would catch nothing — change the
format, regenerate, everything passes.

So: **nothing in a build or a test run may regenerate them.** Producing new
ones when the format genuinely changes is a deliberate act, and the contract
revision machinery makes it a visible one — the fingerprint moves, the suite
goes red, and it stays red until the revision is bumped and the
[changelog](../contract-changelog.md) says what an implementer must do.

That is the same arrangement as `alembic revision --autogenerate`: a
convenience for producing the artifact, a human deciding to commit it, and a
check that refuses to go green while the bookkeeping is missing.
