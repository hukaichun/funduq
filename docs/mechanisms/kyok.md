# Keep your own key (KYOK)

Part of [funduq's mechanisms](../mechanisms.md).

Running an agent costs LLM tokens, and the obvious arrangement — hand
your API key to whoever hosts the agent — leaves the credential on
infrastructure you don't control. KYOK inverts it: the agent's host never
holds the key. The agent still writes ordinary code that calls "an LLM";
it is calling funduq, and funduq relays each completion to an **LLM
provider** — a first-class provider that registered and attached with the
same identity machinery as any agent provider, holds a real key, and
serves the completion under its own policy.

## Binding

A caller opts a run in with `metadata.kyok`, naming an offering
(`providerKey` + model name) and optionally a `context` — a field funduq
relays to the LLM provider untouched and never interprets; what it means
is between the two ends. The binding is checked against the durable
roster at run start (a typo fails the run immediately, not on the first
completion) and names an offering, not a connection — the provider can
drop and re-attach mid-run.

When a bound run delegates, funduq itself copies the binding to the child
run — never the delegating agent, which would otherwise be an agent
holding the caller's `context`. One opt-in therefore covers a run tree,
and the LLM provider polices the tree's shape with the material each
completion carries.

## Authorizing a completion

The agent's `api_key` is a run-scoped bearer token — HMAC-signed by funduq,
carrying exactly the run id, the agent's identity, and an expiry. Three
checks gate every call: the token is funduq's own and unexpired; the run it
names is still live for that agent (a leaked token dies with its run, not
with its TTL); and the call itself is signed, fresh, by the agent
provider's own key over the token, a timestamp, and the request body's
hash.

## No queue, and not as a trade-off

Every other door funduq opens holds a gap: a message arrives when the
caller chooses and the agent's loop accepts it when *it* chooses, and
funduq carries it in between. KYOK has no such gap and no queue, and the
reason is structural rather than operational.

The other doors deliver *into* an agent's loop. KYOK **is** that loop's
own model call, relayed outward — the segment at the top of the loop that
nothing can be injected into, because the party who would wait is the
party already blocked on it (see [the agent loop](../agent-loop.md)). So
none of the gap's four questions apply: nobody is waiting but the asker.
A detached provider fast-fails for the same reason — holding the call
would stall the very loop that made it.

## Serving, refusing, and what funduq relays

Each delivered completion carries the run id, the *proven* calling-agent
identity, which model was addressed, the `context`, and the run's actor
chain — everything a policy needs, with no need to trust funduq's summary.
Wire shapes are OpenAI's chat completions, unmodified. A refusal raised
as `CompletionRefused(payload)` reaches the calling agent **as data** —
funduq relays the payload intact; the vocabulary inside is the parties'
own. Any other failure is an unstructured error. funduq counts what it saw
(served, refused, failed — see
[quality counters](quality.md)) and decides nothing.

## How a refusal reaches the caller

A refusal is the LLM provider's policy working, not an error funduq has an
opinion about — so funduq relays it as **data** and reads none of it.

The provider raises `CompletionRefused(refusal)` carrying its own dict.
funduq picks the payload off by attribute name, duck-typed: the two
packages do not import each other, and the attribute name itself is
pinned in the contract so it cannot drift. Anything that is not a dict
is not treated as a structured refusal.

There are two shapes, depending on where the caller is when it happens:

- **Before the stream starts**, it surfaces as `KyokRejected` carrying
  the provider's refusal and a status. The statuses are a fixed map:
  401 for a bad token or signature, 400 for a malformed body, 403 for an
  inactive run or an unregistered agent, 503 for a missing binding or a
  detached provider, 502 for the provider's own call failing.
- **Mid-stream**, the relay yields one final `CompletionFailure` carrying
  the same payload — as *data*, not as a frame. By then the caller is
  holding an open stream and there is no status left to change, so the
  failure has to travel in band; but which band, and what terminates it,
  is the gateway's. That is also the only place the question "does a
  failed stream still get its `[DONE]`?" can be answered, because only
  the gateway knows which wire's conventions apply. It used to be
  answered here, in core, with "no" — and a client that waited for the
  sentinel waited forever.

An exception that is not a structured refusal collapses to plain prose
instead, and the quality counters record it as `failed` rather than
`refused`. Both are counted; neither is judged — see
[quality counters](quality.md).

The full design record, including the two prior designs this replaced and
why they failed, is
[`design/keep-your-own-key.md`](https://github.com/hukaichun/funduq/blob/d78d0638c0ec2126167240c62471651b5468d35b/design/keep-your-own-key.md).

## Design records

Why this is shaped the way it is, and what it was shaped like first:

- [KYOK replaced two designs, both failing for one reason](../design-records.md#kyok-replaced-two-designs-both-failing-for-one-reason)
- [An inter-chunk timeout kills slow models and blames the wrong side](../design-records.md#an-inter-chunk-timeout-kills-slow-models-and-blames-the-wrong-side)
- ["Trustless" binding was rejected as false safety](../design-records.md#trustless-binding-was-rejected-as-false-safety)
