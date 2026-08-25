"""The exact bytes each party signs, and nothing else.

One function per act, each returning the canonical byte string. They are
pure and take no key: producing the bytes and holding a private key are
different jobs, and keeping them apart is why this package can sit under
both core and an SDK without either lending the other its custody.

**The domain tag on every payload is load-bearing.** It is what stops a
signature made for one act being replayed as another — a resolution can
never be spent as a cancel, and a provider's connect proof can never be
reflected back as funduq's answering one. Adding an act means adding a tag,
never reusing a neighbour's.

Two families live here, and which one an act belongs to is a design
decision recorded in `docs/design-records.md` under "The verifier chooses
the freshness":

- **timestamp family** — resolve, cancel, delegation, KYOK calls. The
  signer picks the moment and the verifier checks it against a window. Safe
  only where the act is singular or idempotent, because a signature is
  replayable for the whole window by anyone who saw it.
- **challenge family** — opening a link. The verifier contributes a nonce
  it destroys on use, so a recording is worthless. Connect authentication
  is deliberately not in the timestamp family; that hole shipped twice.
"""

from __future__ import annotations


_KYOK_CALL = "funduq-kyok-call"
_CONNECT_PROVIDER = "funduq-connect-provider"
_CONNECT_FUNDUQ = "funduq-connect-funduq"
_DELEGATE = "funduq-delegate"
_RESOLVE = "funduq-resolve"
_CANCEL = "funduq-cancel"


def provider_connect_payload(
    funduq_public_key: str, funduq_nonce: str, provider_nonce: str
) -> bytes:
    """The bytes a provider signs to authenticate opening a link.

    Freshness is the verifier's: `funduq_nonce` is a ticket funduq issued to
    this provider's key and destroys on use, so a recorded exchange is
    worthless to whoever recorded it — and a ticket that leaks is worthless
    too, since only the key it names can sign this. `provider_nonce` is the
    provider's own challenge for funduq's answering proof.

    `funduq_public_key` names the recipient: the funduq the provider means to
    connect to (its pinned key; empty string for a funduq with no identity),
    so a proof handed to one funduq cannot be relayed to attach at another —
    the verifying funduq builds this payload with its *own* key and a
    mismatch fails the signature. The role in the domain tag keeps this proof
    and funduq's answering one from ever being the same bytes.

    **What the provider will serve is not in here**, and does not need to be:
    the names were bound in when the ticket was an anonymous nonce anyone
    could answer, so that a captured proof could not be replayed to serve a
    different agent. A single-use ticket naming one key cannot be replayed at
    all. Opening a link and putting a name live are two acts now, and the
    second one happens on the open link.
    """
    return f"{_CONNECT_PROVIDER}:{funduq_public_key}:{funduq_nonce}:{provider_nonce}".encode()


def funduq_connect_payload(funduq_nonce: str, provider_nonce: str) -> bytes:
    """The bytes funduq signs to prove itself to a connecting provider.

    Covers the provider's nonce (the provider chose the freshness) and
    funduq's own, under a role tag distinct from the provider's proof so
    neither can be reflected as the other. This is the payload behind
    "letting a provider pin funduq by its public key": a provider verifies it
    against the funduq key it pinned before producing anything worth
    stealing.
    """
    return f"{_CONNECT_FUNDUQ}:{funduq_nonce}:{provider_nonce}".encode()


def kyok_call_payload(bearer: str, timestamp: int, body_hash: str) -> bytes:
    """The bytes an agent provider signs to prove it made a given KYOK completion call.

    Bound to the bearer token, the timestamp, and a hash of the request body,
    so a captured signature cannot be replayed for a different call.
    """
    return f"{_KYOK_CALL}:{bearer}:{timestamp}:{body_hash}".encode()


def delegation_payload(delegate_public_key: str, expires_at: int) -> bytes:
    """The bytes a durable key signs to name a session key: "SK acts for me until T".

    The session delegation certificate is custody's bridge — a passkey or an
    SSO-custodied key signs once per session and the ephemeral key signs
    everything after. It exists because chain *extension* is provenance
    anyone may perform: delegating authority to a named key takes this
    explicit statement. `expires_at` is the session's lifetime, which is a
    different layer from anything a hop carries — a hop carries no time at
    all.
    """
    return f"{_DELEGATE}:{delegate_public_key}:{expires_at}".encode()


def resolve_payload(run_id: str, timestamp: int) -> bytes:
    """The bytes an authority signs to answer a paused ask: "I resolve this run, now".

    A resolution is singular — the status-guarded reopen picks one winner and
    consumes the signature with it — so it belongs to the timestamp family,
    not the challenge family: the timestamp is checked against a freshness
    window, and a stored signature is spent by the time anyone can read it.
    """
    return f"{_RESOLVE}:{run_id}:{timestamp}".encode()


def cancel_payload(run_id: str, timestamp: int) -> bytes:
    """The bytes an authority signs to ask that a run be stopped: "I ask this run to stop, now".

    Same family as a resolution, for the same reason: cancelling is a
    singular act, not a repeated one needing a challenge. A separate tag so a
    resolution signature can never be replayed as a cancel, or the reverse.
    """
    return f"{_CANCEL}:{run_id}:{timestamp}".encode()
