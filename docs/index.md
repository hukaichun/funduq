# funduq

funduq is a relay for AI agents: providers connect out to it — from a
laptop, behind NAT, inside a private subnet — and funduq opens the doors
callers walk through. It carries standard protocols unchanged, verifies
every identity it is shown, and intervenes in nobody's behavior. The
core is a network-free Python library; putting it on a wire is a
downstream job.

**[What each half is for](responsibilities.md)** — funduq's job, the
contract package's, the provider SDK's, and what none of them do. Read this
first; everything else is detail under one of these.

**[The integration contract](integration-contract.md)** — the declaration to
anyone plugging in. Callers speak AG-UI or A2A with a standard client,
unmodified, and every funduq invention on that side is opt-in.

**[The agent loop](agent-loop.md)** — what a provider's agent actually
receives and sends, turn by turn.

**[What a deployment has to know](operational-limits.md)** — the limits that
are real today, measured rather than estimated.

**[The SDKs](sdks.md)** — the packages providers build with, and what each
publishes.

**[Writing a transport](writing-a-transport.md)** and **[the link protocol
machine](link-protocol-machine.md)** — core hands back objects and pure
functions; these are how you put them on a wire.

**[Contract changelog](contract-changelog.md)** — what changed for anyone who
wrote code against funduq, and **[releasing](releasing.md)** — how a version
reaches PyPI.

The byte-level authority behind all of it is
[`contract-vectors.json`](contract-vectors.json), consumed by funduq's own
test suites and replayable by an implementation in any language. Serving —
HTTP, WebSockets, deployment — lives downstream in
[funduq-server](https://github.com/hukaichun/funduq-server).
