from __future__ import annotations

def _delivered_run_fields() -> frozenset[str]:
    """Read off `DeliveredRun` rather than typed out beside it."""
    from funduq_contract import DeliveredRun

    return frozenset(DeliveredRun.model_fields)


DELIVERED_RUN_FIELDS = _delivered_run_fields()

LINK_REPORT_METHODS = {
    "report_event": ("run_id", "event"),
    "finish_run": ("run_id",),
}

LINK_QUERY_METHODS = {
    "thread_messages": ("thread_id", "limit"),
}

CONNECTED_PROVIDER_ATTRS = frozenset(
    {"public_key", "max_concurrent_runs", "deliver", "cancel"}
)


def _registration_fields() -> frozenset[str]:
    """Read off `Registration` rather than typed out beside it."""
    from funduq_provider_sdk.provider import Registration

    return frozenset(Registration.model_fields)


REGISTRATION_FIELDS = _registration_fields()
