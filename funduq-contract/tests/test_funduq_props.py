from funduq_contract import OBSERVED_METADATA_KEY, FunduqProps, KyokForwardedProps


def test_what_funduq_wrote_reads_back():
    written = FunduqProps(kyok=KyokForwardedProps(token="t"), addressed_run_id="run_1", actor_chain=["hop"])
    props = {"caller": "theirs", OBSERVED_METADATA_KEY: written.model_dump(by_alias=True, exclude_none=True)}

    assert FunduqProps.of(props) == written


def test_nothing_readable_reads_as_empty():
    for props in (None, "not a bag", {}, {OBSERVED_METADATA_KEY: "no"}, {OBSERVED_METADATA_KEY: {"unknown": 1}}):
        assert FunduqProps.of(props) == FunduqProps()
