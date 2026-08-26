from __future__ import annotations

import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# The format lives in funduq-contract now, and these names are re-exported
# rather than rewritten. This module used to carry its own copy of every
# payload below — a second opinion that turned out to be an echo: the reason
# it existed was that this package must not depend on *core*, which is still
# true, and which funduq-contract satisfies without anyone writing the bytes
# twice.
from funduq_contract import (
    ChainResult as VerifiedChain,
    DispatchTarget,
    Hop,
    InvalidChain,
    cancel_payload,
    delegation_payload,
    extend_chain as _extend_chain,
    funduq_connect_payload,
    kyok_call_payload,
    new_chain as _new_chain,
    new_nonce,
    provider_connect_payload,
    resolve_payload,
    sign_hop as _sign_hop,
    verify_chain,
    verify_signature,
)


class WrongFunduq(Exception):
    """The funduq answering a link-open did not prove the key you pinned.

    Raised before any run or event has crossed — the point of the pin is
    refusing to produce anything worth stealing for an imposter."""


class ProviderIdentity:
    """An Ed25519 keypair identifying a provider; `public_key` is its 64-char hex-encoded public key."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self.public_key = private_key.public_key().public_bytes_raw().hex()

    @classmethod
    def generate(cls) -> "ProviderIdentity":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def load_or_create(cls, path: str | Path) -> "ProviderIdentity":
        """Loads the private key at `path` if it exists, else generates one and writes it there (mode 0600).

        Calling this again with the same path yields an identity with the same `public_key`, so a
        restarted process keeps its identity.
        """
        path = Path(path)
        if path.exists():
            return cls(Ed25519PrivateKey.from_private_bytes(path.read_bytes()))
        identity = cls.generate()
        path.write_bytes(
            identity._private_key.private_bytes_raw()  # noqa: SLF001 - own field
        )
        path.chmod(0o600)
        return identity

    def sign(self, payload: bytes) -> str:
        """Signs arbitrary bytes and returns the hex-encoded Ed25519 signature."""
        return self._private_key.sign(payload).hex()

    def sign_connect(
        self, funduq_public_key: str, funduq_nonce: str, provider_nonce: str
    ) -> str:
        """Signs `provider_connect_payload(...)`: this provider's answer to the ticket
        funduq issued to this key, bound to the funduq key it means to connect to.

        What this link will serve is not in here. Opening the link proves the
        key; publishing an agent and putting it live is a separate act, on the
        open link (`ProviderRuntime` does it for you).
        """
        return self.sign(
            provider_connect_payload(funduq_public_key, funduq_nonce, provider_nonce)
        )


    def sign_delegation(self, delegate_public_key: str, ttl_seconds: int = 8 * 3600) -> dict:
        """Issues a session delegation certificate: this identity (the durable authority)
        names `delegate_public_key` to act for it until now+`ttl_seconds`. Returns the wire
        form `{authorityPublicKey, delegatePublicKey, expiresAt, signature}` that
        `funduq.identity.verify_delegation` accepts. The certificate alone moves nothing
        without the delegate's private key, so it is safe to store and relay."""
        expires_at = int(time.time()) + ttl_seconds
        return {
            "authorityPublicKey": self.public_key,
            "delegatePublicKey": delegate_public_key,
            "expiresAt": expires_at,
            "signature": self.sign(delegation_payload(delegate_public_key, expires_at)),
        }

    def sign_resolution(self, run_id: str, timestamp: int | None = None) -> tuple[str, int]:
        """Signs the resolution of a paused run: `(signature, timestamp)` over
        `resolve_payload(run_id, timestamp)`. Singular operation, timestamp family — funduq
        checks the timestamp against its 60s freshness window and the status-guarded reopen
        consumes the signature with the win."""
        timestamp = int(time.time()) if timestamp is None else timestamp
        return self.sign(resolve_payload(run_id, timestamp)), timestamp

    def sign_cancel(self, run_id: str, timestamp: int | None = None) -> tuple[str, int]:
        """Signs a request that a run be stopped: `(signature, timestamp)` over
        `cancel_payload(run_id, timestamp)`. Singular operation, timestamp family — funduq
        checks the timestamp against its 60s freshness window.

        Needed only for a run whose thread bound an authority at birth; an
        unbound run is cancellable by anyone who can address it, as before.
        """
        timestamp = int(time.time()) if timestamp is None else timestamp
        return self.sign(cancel_payload(run_id, timestamp)), timestamp

    def sign_hop(self, prev_token: str | None = None) -> str:
        """One actor-chain hop under this identity's key, linked to `prev_token`.

        The format is `funduq_contract.sign_hop`; this is the custody half —
        the key stays here, the bytes are agreed elsewhere.
        """
        return _sign_hop(self._private_key, prev_token)

    def new_chain(self) -> list[str]:
        """Starts a chain headed by this identity."""
        return _new_chain(self._private_key)

    def extend_chain(self, prev_chain: list[str]) -> list[str]:
        """Appends a hop signed by this identity. Extension is provenance, not
        authorization: the head stays the segment's authority."""
        return _extend_chain(self._private_key, prev_chain)
