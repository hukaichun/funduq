from __future__ import annotations

from collections.abc import AsyncIterator
from openai.types.chat import ChatCompletionChunk

from funduq_provider_sdk.llm import (
    DeliveredCompletion,
    InProcessLLMProvider,
    ProviderIdentity,
)


def test_delivered_completion_fields_match_contract():
    assert {"run_id", "llm_name", "body"} <= set(DeliveredCompletion.model_fields)


def _delivered(**overrides) -> DeliveredCompletion:
    base = dict(
        run_id="run_1",
        provider_key="ab" * 32,
        agent_name="translator",
        body={"model": "m", "messages": []},
        llm_name="gpt4",
        context={"voucher": "v1"},
        actor_chain=["jwt1", "jwt2"],
    )
    base.update(overrides)
    return DeliveredCompletion(**base)


async def test_inprocess_provider_hands_its_llm_the_delivered_completion_untouched():
    seen: list[DeliveredCompletion] = []

    async def llm(delivered: DeliveredCompletion) -> AsyncIterator[ChatCompletionChunk]:
        seen.append(delivered)
        return
        yield  # pragma: no cover — makes this an async generator

    provider = InProcessLLMProvider(ProviderIdentity.generate(), llm)
    request = _delivered()
    async for _ in provider.complete(request):
        pass

    assert seen == [request]


def test_public_key_is_the_identitys_own():
    identity = ProviderIdentity.generate()
    assert InProcessLLMProvider(identity, llm=None).public_key == identity.public_key


async def test_any_link_receives_the_published_shape_itself():
    from funduq_provider_sdk.llm import FunduqLLMLink

    seen: list[DeliveredCompletion] = []

    class RecordingLink(FunduqLLMLink):
        @property
        def public_key(self) -> str:
            return "abc123"

        def complete(self, request: DeliveredCompletion) -> AsyncIterator[ChatCompletionChunk]:
            seen.append(request)

            async def _nothing():
                return
                yield

            return _nothing()

    request = _delivered(run_id="r-1", provider_key="k", agent_name="a",
                         context={"voucher": "v"}, actor_chain=["hop0"])
    async for _ in RecordingLink().complete(request):
        pass

    (delivered,) = seen
    assert delivered is request
    assert (delivered.context, delivered.actor_chain) == ({"voucher": "v"}, ["hop0"])


async def test_the_readme_ceiling_pattern_refuses_structurally():
    from funduq_provider_sdk.llm import CompletionRefused

    spent: dict[str, int] = {}

    async def guarded(delivered: DeliveredCompletion):
        spent[delivered.run_id] = spent.get(delivered.run_id, 0) + 1
        if spent[delivered.run_id] > 2:
            raise CompletionRefused({"kind": "budget-ceiling", "runId": delivered.run_id})
        return
        yield

    provider = InProcessLLMProvider(ProviderIdentity.generate(), guarded)
    request = _delivered(run_id="r-capped", provider_key="k", agent_name="a")
    for _ in range(2):
        async for _ in provider.complete(request):
            pass
    try:
        async for _ in provider.complete(request):
            pass
        raise AssertionError("third completion was served past the ceiling")
    except CompletionRefused as e:
        assert e.refusal == {"kind": "budget-ceiling", "runId": "r-capped"}
