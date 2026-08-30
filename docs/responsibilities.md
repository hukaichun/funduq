# What each half is for

Two packages, one boundary. Everything either side does is here; anything not
here is not its job.

## funduq

**Holds who is serving what, as a fact.** A provider opens a link and
publishes names on it. `serving(agent)` is a lookup, never a deduction from a
timestamp — funduq holds the provider object or it does not.

**Proves a key once, when the link opens.** A ticket funduq issued to that
key, signed with funduq's own key named in the bytes, answered by funduq
signing the provider's nonce back. Nothing after that is signed: the open link
is the credential.

**Persists threads, runs, events and messages**, and answers questions about
them.

**Hands a run to whoever is serving its agent**, one conversation's turn at a
time. The next utterance of a conversation waits for the one before it to be
claimed; nothing wider waits.

**Records only what it observed.** A run is `failed` because funduq saw it
fail, not because a clock ran out on something funduq cannot see. It asks a
provider to stop; it cannot make one, and it never writes an outcome the
provider's own output could contradict.

**Relays events untouched.** An event type funduq does not know is passed
through, not filtered and not wrapped.

**Counts what it observed about a provider** — declined while claiming room,
took work and never ended it, never answered — and stops serving one that
spends its allowance. Counting is not judging: the counters say what happened.

**Verifies an actor chain** and hands back the hops. It authors no digest of
one and does not vouch for a presenter.

**Implements no transport.** funduq's own code neither listens nor dials.
Which protocol something arrived over is not a thing core knows.

## funduq-contract

**Writes the bytes both sides sign, once.** Payload builders, signature
verification, chain hops, and the revision number an installed package can
answer with. Nothing else. It is a dependency of both other packages so that
neither restates the other's bytes.

## funduq-provider-sdk

**Gives a provider author a way to write an agent** — a `Provider`, an
`AgentHandle`, and a `ProviderRuntime` that queues delivered runs, executes
each, and reports back through whatever link it is on.

**Declares the wire forms** a transport carries: `DeliveredRun`,
`Registration`, `DeliveredCompletion`. Each is the published shape, dumped and
rebuilt by the models rather than by hand.

**States the port a transport implements** — `FunduqLink` — and provides the
in-process one, which goes through the same handshake as any other because
sharing a process is not a reason to be trusted.

**Never imports funduq.** A provider runs in a different process with no
access to core's code, and core drags a database stack behind it. The two are
contract-coupled, not code-coupled.

## What neither of them does

**Neither owns a socket.** Listening, dialling, TLS, framing and the enrolment
channel that carries a ticket to a provider belong to the serving layer, which
is a different repository.
