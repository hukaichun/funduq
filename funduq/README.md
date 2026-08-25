# funduq

The network-free core: agents, threads, runs, dispatch, and the protocol
adapters. A library you embed, not a server you run.

```
pip install funduq              # SQLite, the zero-config default
pip install "funduq[postgres]"  # for a real multi-writer deployment
```

**This package implements no transport: its code neither listens nor dials.**
Serving — an HTTP or gRPC binding for the AG-UI and A2A doors — lives
downstream, in [funduq-server](https://github.com/hukaichun/funduq). What is
here is everything that decides: the roster, the run record, dispatch to a
connected provider, and translation at the doors.

Two protocols are quoted rather than transcribed. AG-UI shapes come from
`ag-ui-protocol` and A2A's from `a2a-sdk`, including the method names, so a
protocol rename fails at import here instead of at a client six months later.

## What you get

- **Agents, threads and runs** — a run is one turn of an agent's loop, with
  its identity held across a pause for a human, so work can span hours.
- **Dispatch** — runs offered to whichever provider is serving, per-thread
  ordering, declared concurrency, and quality counters for what funduq can
  see from where it stands.
- **Doors** — AG-UI and A2A adapters over one seat, so which protocol a
  request arrived by changes nothing about how it is decided.
- **Identity** — providers prove a key to connect, callers may carry an
  actor chain, and neither is optional for being in-process.

## Read before deploying

[What a deployment has to know](https://hukaichun.github.io/funduq/operational-limits/)
— in particular that **core's caller doors are not independently safe**:
verifying a chain is not authenticating a caller, and a door has no live
channel to do the second.

## Its companions

| | |
|---|---|
| [`funduq-contract`](https://pypi.org/project/funduq-contract/) | the bytes both sides sign — core depends on it, and so does the SDK |
| [`funduq-provider-sdk`](https://pypi.org/project/funduq-provider-sdk/) | what a provider implements, with `[llm]` for completions |

Apache-2.0. Docs at <https://hukaichun.github.io/funduq/>.
