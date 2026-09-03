# funduq

[![CI](https://github.com/hukaichun/funduq/actions/workflows/ci.yml/badge.svg)](https://github.com/hukaichun/funduq/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Protocol: AG-UI & A2A](https://img.shields.io/badge/Protocols-AG--UI%20%7C%20A2A-blue.svg)](docs/integration-contract.md)

**funduq is the seat between a caller and an agent provider.** The agent stays where its owner runs it, under its owner's key — a laptop, a private VPC, an office behind NAT — and connects *outbound*; funduq makes it reachable over standard [AG-UI](https://docs.ag-ui.com/) or [A2A](https://a2a-protocol.org/), holds each run, and records who asked and through whose hands the work passed.

**It is not an agent framework.** It does not write your agent, choose your model, or run your prompts. There is no chain, no graph, and no opinion about how an agent thinks.

**It is not a server, either.** This repository is the mechanism — a Python library with no socket in it — plus the contract every party speaks. Putting it on a wire is a deployment's decision, made downstream; the reference deployment is [funduq-server](https://github.com/hukaichun/funduq-server).

## Why it exists

Agents are built and run by different owners in different places, and the moment one is called across an owner's boundary two things go missing. *Reachability*: the agent has to be hosted somewhere the caller can reach, which is exactly what a laptop, a private subnet or a NAT'd office does not offer. *The record*: who asked, and through whose hands the work passed before it landed, exists only in whichever party's logs happened to keep it — and each party keeps its own. funduq is a third seat that supplies both without taking a side: it never speaks in a guest's name and never decides what an agent may do, so a caller and a provider that share nothing but the two standard protocols can still do business, and one register says what happened.

That seat is not a category anyone invented for this. A 2026 survey of agentic-web infrastructure ([arXiv 2606.20570](https://arxiv.org/pdf/2606.20570)) lists as still-unsolved exactly three things: an intermediary between callers and agent providers, responsibility tracked across delegation hops, and a run's lifecycle held by someone other than the two parties.

## Why the core carries no wire

A wire is a set of concrete choices — FastAPI or gRPC, one port or two, WebSocket relays or long-polling, which TLS terminator sits in front, what the corporate proxy will and will not pass. **None of those choices has an answer until there is a deployment to ask.** An enterprise intranet and a public endpoint answer them differently; so do a single node and a fleet of replicas; so does a network with a Zscaler in the middle.

The mechanism does not need those answers. What a run *is*, when it has settled, whose signature may answer its pause, which turn a message belongs to, how the record is built — all of that is decided before anyone picks a framework, and would be decided the same way whichever one they pick. So the core is deliberately peeled away from protocol: it does not choose a transport, because choosing one would let a decision that belongs to a deployment reach back and shape a mechanism that never depended on it.

Two consequences follow, and both are checked rather than promised:

- **The core's own code never listens or dials** — behaviourally (importing the package performs no socket operation) and statically (no core module imports a transport, or a protocol SDK's I/O half). The check forbids *verbs*, not *nouns*: `a2a-sdk` ships `httpx` in its belly, and quoting a protocol's own package is exactly how funduq stays current with it. See `funduq/tests/test_core_is_network_free.py`.
- **Which protocol something arrived over is not a thing the core knows.** `broker.py`, `identity.py` and `repo.py` name no protocol; a run reaches the broker as a built input, whether it came through the A2A adapter, the AG-UI adapter, or an in-process call. In-process is a transport, not a special case: it goes through the same handshake as any other.

The line this draws is one sentence: **what a protocol *says* is the core's; how it is *sent*, and *who may say it*, are the deployment's.** A JSON-RPC envelope, an SSE frame, an HTTP status, a version header, a rate limit, an allowlist — all *sent* or *who*, none of them *what*. Core hands back objects (an AG-UI event, an A2A `Task`, an OpenAI chunk) and knows no more about a caller than that caller's own signature proves. Today's reference deployment carries the provider link over a WebSocket on one HTTP port; it was a gRPC stream once, and the core was untouched by the swap — which is the test of whether this boundary is real.

---

## What the core gives you

- **Keep your own agent.** The industry has a name for letting an outside agent into a platform: *bring your own agent*. funduq turns the verb around. The agent is not brought anywhere — its code, its prompts, its tools and its credentials stay on its owner's machine under its owner's key, and the only thing that crosses the link is the standard shape of a run and its events. It is the same promise Keep Your Own Key makes about an API key, made about the agent itself: custody does not move; funduq carries shapes.
- **Reachability without ingress, as a port.** A provider opens a link *to* funduq and publishes the agents it serves on it; work is offered back over that link. The link is a small, transport-free port — offer / verdict, report events / finish, a cancel that is a request and never a command — specified in [the provider link](docs/provider-link.md) and implemented by whatever carrier a deployment chooses.
- **Two protocols, one run.** A caller speaks AG-UI (human-facing event streaming) or A2A v1.0 (agent-to-agent), with a stock client, unmodified. Both are translated into one AG-UI-shaped run input before dispatch, so an agent's author writes one shape and is callable through both doors. Both wire vocabularies are quoted from the official packages (`ag-ui-protocol`, `a2a-sdk`) — a spec rename fails at import instead of rotting silently.
- **Keypair identity, no accounts.** A provider is an Ed25519 keypair; opening a link answers a single-use challenge signed by that key, and the open link is the credential. There is no user database and no central authority vouching for what an agent *does* — a caller can confirm it is talking to the same key as last time, and nobody's seal claims more than that.
- **Responsibility chains.** A caller may attach an actor chain — each hop a signed JWT bound to the previous hop's hash — and a thread whose first run carries one binds the chain's head at birth. From then on only the head or the serving provider may write to it, answering its paused ask takes a signature over that exact ask, and asking one of its runs to stop takes the same authority. Every funduq-invented mechanism on the caller side is **opt-in**: leave the chain off and the thread behaves as plain AG-UI/A2A forever. Specified in [the integration contract](docs/integration-contract.md); enforced in `doors.py` and `identity.py`; 38 tests.
- **Durable threads, runs, and human-in-the-loop.** Conversation state persists; `input-required` pauses a run and a signed answer resumes it. SQLite by default with zero configuration; one `database_url` moves the same code path to Postgres.
- **A record built in order.** Everything that happens to a run — the offer, the provider's verdict, each event, the finish — enters through a door and is written by the run's one owner in arrival order. The record says what funduq observed and nothing it did not: a run that finishes despite a cancel request records `completed`, because that is what happened.
- **Keep Your Own Key** *(experimental)*: callers fund an agent's LLM calls with their own key without handing the raw credential to the agent's host — the completion is relayed to an LLM provider the caller names. The design note is [kept in history](https://github.com/hukaichun/funduq/blob/d78d0638c0ec2126167240c62471651b5468d35b/design/keep-your-own-key.md).
- **A published contract.** Every byte a party signs, every shape that crosses, and every verb of the provider link is exported by [`funduq-contract`](funduq-contract/) and pinned in [`contract-vectors.json`](docs/contract-vectors.json), replayable in any language; a fingerprint test fails funduq's own CI when the surface moves without a [changelog entry](docs/contract-changelog.md). An implementation never needs funduq's source.

---

## Design principles

A *funduq* is the merchant inn of the old trading cities: it gave a merchant with no address in town the three things it takes to trade there — a place to be reached, a house whose register recorded the dealings, and a keeper who kept the house without meddling in the trades. The keeper did not vouch for anyone's goods; you recognized a merchant because the same face returned to the same house season after season. funduq is that house, built as software, and these invariants are load-bearing in the shipped code:

- **The keeper never speaks in a guest's name.** funduq can *ask* an agent to stop; it cannot make it. It relays events untouched — an event type it does not know is passed through, not filtered and not wrapped — and it never writes an outcome the provider's own output could contradict.
- **The same face, season after season.** Identity is a key, not an account. Sharing a process earns no shortcuts: an in-process provider passes the same registration, identity and liveness checks a remote one does.
- **The house provides mechanism; the host decides policy.** Who may register, who may call, what a key is allowed to do, how long a thing may wait — these are a deployment's decisions, made in front of the door. The core records facts and demands proof from the keys those facts name; anything that would *manufacture* authority is policy, and policy lives where the wire does. Open-by-default is funduq's own stance, not a constraint it imposes: the same core serves an invite-only intranet and a public directory.
- **Counting is not judging.** funduq counts what it observed about a provider — declined while claiming room, took work and never ended it, never answered — and stops serving one that spends its allowance. The counters say what happened; what a count *means* is the reader's call.
- **Anyone may walk in.** A stock AG-UI or A2A client works unmodified. That is a hard rule with a test behind it, and it has teeth in both directions: when funduq seems to need a new field or endpoint, the first question is whether the protocol already has one — and the answer has changed designs before.

Parts of the conversation semantics are under open discussion with the protocol communities: [who answers a delegated `input-required`](https://github.com/a2aproject/A2A/discussions/2148), [the multi-turn gap list](https://github.com/a2aproject/A2A/issues/1992), and [in-flight steering for AG-UI](https://github.com/ag-ui-protocol/ag-ui/issues/2148).

---

## Two repositories, one boundary

| | **funduq** (this repo) | **[funduq-server](https://github.com/hukaichun/funduq-server)** |
|---|---|---|
| **Owns** | The mechanism: agents, threads, runs, identity, persistence, protocol *translation* — and the contract every party speaks | One deployment of it: ports, transports, TLS, CORS, endpoints, wire framing, admin surface |
| **Ships** | [`funduq`](funduq/) (the core library), [`funduq-contract`](funduq-contract/) (the bytes both sides sign and the shapes that cross), [`funduq-provider-sdk`](funduq-provider-sdk/) and its `[llm]` extra (the provider's side of the port) | The reference gateway, the transport SDKs (`funduq-agent-sdk`, `funduq-client-sdk`), the reference providers, a directory UI |
| **May it bind a socket?** | Never — checked by test | Yes; that is its entire job |
| **Decides who may speak?** | Only what a caller's own signatures prove. Beyond that, nothing tells the core who is on the other end | Yes: authentication, authorization, rate limits, and whatever gate a deployment wants in front of the door |

Three consequences, recorded in [funduq#27](https://github.com/hukaichun/funduq/issues/27):

- **No network design originates here.** When a need looks network-shaped, it becomes a core mechanism *plus* a serving decision made downstream — never a new endpoint, transport, or subproject in this repo.
- **The wire contract is authored downstream.** funduq-server's [`docs/server-mode.md`](https://github.com/hukaichun/funduq-server/blob/main/docs/server-mode.md) is the spec of record for its wire; the SDKs here implement the port, they do not define a carrier.
- **The core's doors are not independently safe.** They attribute and record; they do not authenticate a live caller. Whatever stands in front of them does that, and a deployment that exposes them bare has made a decision this repo cannot make for it. What a deployment has to know is in [operational limits](docs/operational-limits.md).

One deployment shape, the reference one:

```
                           Public Internet
                               │
┌──────────────────────────────▼────────────────────────────────┐
│               a funduq gateway (funduq-server)                 │
│        one HTTP surface · relay engine · funduq core inside     │
│                SQLite / Postgres durable state                 │
└──────┬─────────────────────────────────────────┬──────────────┘
       │ HTTP (AG-UI SSE / A2A JSON-RPC)          │ outbound-only persistent links
       │ any caller can reach                     │ providers connect out to
       ▼                                          ▼
 ┌─────────────┐   ┌───────────────┐   ┌──────────────┐   ┌────────────────────┐
 │ Browser /   │   │ External Agent│   │ Alice's Agent│   │ Bob's Agent        │
 │ Web UI      │   │ (A2A Caller)  │   │ (Laptop/NAT) │   │ (Private VPC)      │
 └─────────────┘   └───────────────┘   └──────────────┘   └────────────────────┘
```

---

## Developing the library

Running anything is funduq-server's quick start, not this repo's. What lives here needs no gateway at all:

```bash
cd funduq && uv sync --group dev
uv run pytest        # SQLite, zero config
```

The same suite runs against Postgres by pointing at one — dialect bugs only ever appear on one side, so run both before merging (this repo's `docker compose` carries a Postgres for exactly this):

```bash
docker compose up paradedb -d
FUNDUQ_DATABASE_URL="postgresql+psycopg://funduq:funduq@localhost:5433/funduq" uv run pytest
```

Configuration is an argument, never ambient state: the core reads no environment variable itself — a deployment reads its own environment and constructs `CoreSettings`. Two of its fields are required and have no default on purpose, `token_signing_secret` and `identity_private_key`; an insecure fallback for either would be a real bypass. Schema changes are Alembic revisions under [`funduq/funduq/alembic/`](funduq/funduq/alembic/); `uv run alembic upgrade head`, run from `funduq/`, is a deploy-time step deliberately separate from anything a running gateway does (see [CONTRIBUTING.md](CONTRIBUTING.md)).

---

## Where it sits

Nothing we know of occupies this exact intersection — outbound-only reachability, AG-UI and A2A translated into one run, keypair identity with signed responsibility chains, durable state with pause/resume, and a core that a deployment puts on whatever wire it has. Each neighbor does its own thing better:

- **a2a-relay** is a much smaller outbound-WebSocket forwarder. If all you need is A2A passthrough with a shared relay token and no state, it is the simpler tool.
- **[agentgateway.dev](https://agentgateway.dev/)** is a serious ingress data plane — RBAC, observability, MCP support, Kubernetes-grade deployment. funduq has none of that; the trade is that it assumes your backends are already reachable, and funduq exists for when they are not.
- **Cloudflare AI Gateway** and the cloud agent platforms (**AWS Bedrock AgentCore**, **Google Vertex / Agent Marketplace**) give you managed operations, billing and SLAs a self-hosted seat never will. The trade is that your agents live inside their cloud and their identity model.

An older comparison, including DID standards and MCP tunnels, is [kept in history](https://github.com/hukaichun/funduq/blob/d78d0638c0ec2126167240c62471651b5468d35b/design/prior-art.md); parts of it have aged.

---

## Repository structure

Independent distributions — no shared workspace, each stands alone:

| Path | What it is |
|---|---|
| [`funduq/`](funduq/) | **The core library.** Agents, threads, runs, identity, the AG-UI / A2A / KYOK adapters, SQLite/Postgres persistence. Picks no transport, by packaging and by test |
| [`funduq-contract/`](funduq-contract/) | **The bytes both sides sign, written once**, and the shapes that cross the link: payload builders, signature verification, chain hops, `DeliveredRun` and friends, and the contract revision an installed package can answer with. A dependency of both other packages so neither restates the other's bytes. Because it carries the crossing shapes, it also carries the protocol types they are built from (`ag-ui-protocol`, `openai` — types only) |
| [`funduq-provider-sdk/`](funduq-provider-sdk/) | **The provider's side of the port**: identity and what it signs, `FunduqLink` (the port a transport implements, with the in-process one included), and `ProviderRuntime`, the worker loop that runs an agent and reports back through whatever link it is on. The `[llm]` extra is the same package serving completions for KYOK. Never imports `funduq`: the two are contract-coupled, not code-coupled. See its [README](funduq-provider-sdk/README.md) |
| [`docs/`](docs/) | The published site — [what each half is for](docs/responsibilities.md), [the integration contract](docs/integration-contract.md), [the provider link](docs/provider-link.md), [operational limits](docs/operational-limits.md), the SDK pages, the [contract changelog](docs/contract-changelog.md) and [`contract-vectors.json`](docs/contract-vectors.json). The *why* lives in git history, not the tree |

Several names circulate and they are different packages: **`funduq-contract`, `funduq-provider-sdk` and `funduq-provider-sdk[llm]` are here** and define the interaction; `funduq-agent-sdk` (a client for the gateway's provider WebSocket) and `funduq-client-sdk` (the caller's side) live in [funduq-server](https://github.com/hukaichun/funduq-server), along with the reference providers and the directory UI. The gateway repo owns both ends of every wire it defines.

---

## Roadmap

Directions, not commitments. If one of these matters to you, open an issue rather than assuming it is underway.

- **Provider reconnection with pending runs held, not failed** — blocked on a prerequisite the code now names ([funduq#220](https://github.com/hukaichun/funduq/issues/220)).
- **Queued runs surviving a restart** ([funduq#122](https://github.com/hukaichun/funduq/issues/122)).
- **Cross-funduq discovery**: `agent@funduq.example.com` addressing with client-side resolution — no inter-funduq proxying. A design note [kept in history](https://github.com/hukaichun/funduq/blob/d78d0638c0ec2126167240c62471651b5468d35b/design/federation-and-anti-abuse.md).
- **Horizontal gateway scaling.** The measured baseline — 0 of 8 scenarios, two real processes, SQLite and Postgres alike — and what each scenario was are in [operational limits](https://hukaichun.github.io/funduq/operational-limits/).

---

## Contributing

Suggestions, issues, and pull requests are welcome — [CONTRIBUTING.md](CONTRIBUTING.md) covers codebase organization and the PR workflow.

**License**: [Apache 2.0](LICENSE)
