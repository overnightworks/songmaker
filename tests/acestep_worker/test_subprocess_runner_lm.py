from __future__ import annotations

import pytest

from acestep_worker.subprocess_runner import LmInitFailedError, stop_acestep_subprocess


def test_start_stops_the_child_when_its_lm_is_missing(fake_uv) -> None:
    health = fake_uv.health(llm_initialized=False)
    with pytest.raises(LmInitFailedError):
        fake_uv.start(health)

    assert not fake_uv.is_alive()


def test_start_keeps_a_child_whose_lm_is_up(fake_uv) -> None:
    handle = fake_uv.start(fake_uv.health(llm_initialized=True))
    try:
        assert fake_uv.is_alive()
    finally:
        stop_acestep_subprocess(handle)


def test_start_does_not_read_the_lm_flag_when_the_lm_is_off(fake_uv) -> None:
    handle = fake_uv.start(fake_uv.health(llm_initialized=False), init_llm=False)
    try:
        assert fake_uv.is_alive()
    finally:
        stop_acestep_subprocess(handle)


@pytest.mark.parametrize(
    ("body", "answer_once"),
    [
        pytest.param(b'{"data": {"llm_initialized": true}}', True, id="unreachable"),
        pytest.param(b"not json", False, id="unparsable"),
        pytest.param(b"[]", False, id="wrong-shape"),
        pytest.param(b'{"data": {}}', False, id="no-flag"),
        pytest.param(b'{"data": {"llm_initialized": "no"}}', False, id="non-boolean"),
    ],
)
def test_start_treats_an_unreadable_health_body_as_no_lm_verdict(
    fake_uv, body: bytes, answer_once: bool
) -> None:
    handle = fake_uv.start(body, answer_once=answer_once)
    stop_acestep_subprocess(handle)
