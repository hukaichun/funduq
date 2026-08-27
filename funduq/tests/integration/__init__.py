"""Tests whose reason for existing is the seam between core and the SDKs.

**Not "everything that imports the SDK".** Most of the suite next door does,
deliberately: `funduq`'s dev dependency comment says the suite registers,
serves runs and serves completions through the SDK a real provider would use,
so the payload a provider actually sends is checked against the one funduq
expects on every run. By that measure 28 of 57 files would be in here, which
would be a folder that means nothing.

What is in here is the narrower thing: a test that would have no reason to
exist if the two packages were one. Four kinds —

- **the ports match**: what the SDK declares against what core supplies;
- **the handshake**: the one exchange where a key is proved, driven from both
  ends;
- **the loopbacks**: the protocol machines against a real `Funduq` and a real
  `ProviderRuntime`, through the codec;
- **behaviour that needs both halves to be true at once** — a conversation
  that waits for its claim rather than for its answer.

Everything else stays beside the core behaviour it is about, using the SDK as
the realistic way to drive it. If a test here would still make sense with core
replaced by a stub, it is in the wrong folder.
"""
