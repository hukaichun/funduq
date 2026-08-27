"""What both sides of funduq agree the bytes are.

Core and the SDKs each used to carry their own copy of this — the same six
signing payloads, the same chain format, the same signature check, under two
sets of names. The split was justified by dependency weight and that part
was sound: nobody should install a database stack to sign a hop. But weight
only says the SDK cannot depend on *core*; it never said to write the format
twice, and the second copy bought nothing the recorded vectors do not
already buy. A frozen byte string catches a wrong change to one shared
implementation exactly as well as it catches two copies drifting apart.

So there is one implementation now, and the vectors keep doing the job they
were actually doing: pinning what the bytes are, for this implementation and
for one written in any other language.

Nothing here holds a private key. Producing the bytes and having custody are
different jobs, which is what lets this sit under core and an SDK at once
without either lending the other its keys.
"""

CONTRACT_REVISION = 9
"""Which revision of funduq's contract this package implements.

Package versions and contract revisions answer different questions. A
version says which release of *this distribution* you have; a revision says
which set of bytes, settings and ports it agrees with, across all four
distributions at once. They move at different rates on purpose — a bug fix
here bumps the version and not the revision.

It is a constant so that an installed package can answer the question
without anyone visiting a web page: `funduq_contract.CONTRACT_REVISION`
against the revision recorded in `docs/contract-vectors.json`, and
`docs/contract-changelog.md` for what moved between them. It is part of the
contract surface, so it cannot be forgotten when a revision is cut — the
fingerprint moves and the suite stays red until it is updated.
"""

from funduq_contract.chain import (
    DispatchTarget,
    Hop,
    ChainResult,
    InvalidChain,
    dispatch_hop,
    extend_chain,
    hop_hash,
    new_chain,
    sign_hop,
    verify_chain,
)
from funduq_contract.payloads import (
    cancel_payload,
    delegation_payload,
    funduq_connect_payload,
    kyok_call_payload,
    provider_connect_payload,
    resolve_payload,
)
from funduq_contract.signatures import (
    FINGERPRINT_HEX_LENGTH,
    is_fingerprint,
    new_nonce,
    provider_fingerprint,
    verify_signature,
)

__all__ = [
    "CONTRACT_REVISION",
    "FINGERPRINT_HEX_LENGTH",
    "ChainResult",
    "DispatchTarget",
    "Hop",
    "InvalidChain",
    "cancel_payload",
    "delegation_payload",
    "dispatch_hop",
    "extend_chain",
    "funduq_connect_payload",
    "hop_hash",
    "is_fingerprint",
    "kyok_call_payload",
    "new_chain",
    "new_nonce",
    "provider_connect_payload",
    "provider_fingerprint",
    "resolve_payload",
    "sign_hop",
    "verify_chain",
    "verify_signature",
]
