from __future__ import annotations

import asyncio
import logging

from typing import TYPE_CHECKING

from ag_ui.core import EventType

from funduq import repo
from funduq.broker import Fail
from funduq.handlers import run_error

if TYPE_CHECKING:
    from funduq.core import Funduq

logger = logging.getLogger("funduq.health")


async def close_with_terminal_event(funduq: "Funduq", run_id: str, failure_reason: str) -> None:
    """Give a run funduq has just failed its terminal `RUN_ERROR`, whether or not
    the broker still tracks it.

    A live run gets a `Fail` pushed into its pipeline, which appends the event
    and relays it to any subscriber. A run the broker has already forgotten —
    a stale pause reaped by the sweep, an orphan reaped at startup — has no
    pipeline and no subscriber left, but the record still owes the verdict: the
    same event is appended directly, so the event stream ends the way the
    database says the run did. A run that already carries its own `RUN_ERROR`
    is left alone, same as everywhere else."""
    if funduq.broker.push(run_id, Fail(failure_reason)):
        return
    async with funduq.session() as session:
        events = await repo.get_run_events(session, run_id)
        if any(e.get("type") == EventType.RUN_ERROR for e in events):
            return
        seq = await repo.get_last_event_seq(session, run_id) + 1
        await repo.append_run_event(
            session, run_id, seq, run_error(failure_reason)
        )
        await session.commit()


async def sweep_once(funduq: "Funduq") -> None:
    """Fails runs stuck paused (input-required) past `paused_timeout_seconds`, and only if
    that setting is configured — it is skipped entirely when it is None.

    It used to fail *claimed* runs too, for going silent past a stall
    timeout. That read silence as death, and a healthy agent's loop is
    silent for most of its life by construction: the model call it is
    waiting on is the un-injectable segment, and funduq cannot see inside
    it. So the verdict fell on slow providers, blaming the party that had
    done nothing wrong — and on runs whose silence funduq itself was
    causing, by holding their KYOK completion.

    How long a provider holds a run is the provider's own business. What
    funduq judges is whether it is *behaving abnormally*, and the fact that
    settles that is whether it is still here — `RunBroker.unregister_
    provider` fails what a departing provider was holding, at once. A
    paused run is different: nobody is holding it, and the deadline is on
    the party that owes an answer.
    """
    settings = funduq.settings
    async with funduq.session() as session:
        stale_paused: list[str] = []
        if settings.paused_timeout_seconds is not None:
            stale_paused = await repo.fail_stale_paused_runs(session, settings.paused_timeout_seconds)
    for run_id in stale_paused:
        await close_with_terminal_event(funduq, run_id, "paused_no_resume")
    if stale_paused:
        logger.warning(
            "health sweep: %d run(s) paused (input-required) past %ds with no resume, marked failed: %s",
            len(stale_paused),
            settings.paused_timeout_seconds,
            stale_paused,
        )


async def run_health_sweeps_forever(funduq: "Funduq") -> None:
    while True:
        await asyncio.sleep(funduq.settings.health_sweep_interval_seconds)
        try:
            await sweep_once(funduq)
        except Exception:
            logger.exception("health sweep failed")
