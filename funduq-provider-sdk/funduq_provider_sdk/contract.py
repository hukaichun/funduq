from __future__ import annotations

DELIVERED_RUN_FIELDS = frozenset(
    {"run_id", "agent_name", "run_input", "thread_id", "metadata"}
)

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
    """Read off `Registration` rather than typed out beside it.

    Two definitions of one shape is the thing that drifts, and this one has a
    test in core's suite comparing it to the keys `register_agents` actually
    reads — which only stays honest if the model is the single source."""
    from funduq_provider_sdk.provider import Registration

    return frozenset(Registration.model_fields)


REGISTRATION_FIELDS = _registration_fields()
