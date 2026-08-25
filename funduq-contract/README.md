# funduq-contract

The bytes both sides of funduq sign and verify: the signing payloads, the
actor-chain hop format, and signature checking. Core depends on it and so
does `funduq-provider-sdk`; neither depends on the other.

```
pip install funduq-contract
```

**It holds no private key.** Producing the bytes and having custody are
different jobs, which is what lets one package sit under core and an SDK at
once without either lending the other its keys. Nothing here talks to a
network or a database; the dependencies are `cryptography` and `pyjwt`.

- `payloads` — one function per act, returning the canonical bytes a signer
  signs. The domain tag on each is what stops a signature made for one act
  being spent as another.
- `chain` — `sign_hop`, `new_chain`, `extend_chain`, `dispatch_hop`, and
  `verify_chain`. A hop carries the signer's key and a hash-link to the hop
  before it, and nothing else — no subject, and no time.
- `signatures` — `verify_signature`, `new_nonce`, provider fingerprints.

## Implementing funduq's contract in another language

Replay [`contract-vectors.json`](https://github.com/hukaichun/funduq/blob/main/docs/contract-vectors.json):
build each payload from its `inputs`, assert the exact `payload_utf8` bytes,
and check `signature_hex` verifies under the published test key. The test key
is for vectors only — never accept it in a real deployment.

The vectors are **recorded, not derived**. They work because they are old, so
nothing in a build or a test run regenerates them: a file dumped from the
code would pass whatever the code happened to do. Producing new ones is a
deliberate act, and the contract revision in that file — with its
[changelog](https://github.com/hukaichun/funduq/blob/main/docs/contract-changelog.md)
— is how you tell whether anything you depend on has moved.
