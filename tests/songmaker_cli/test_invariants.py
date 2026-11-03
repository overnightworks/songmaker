import pytest

from songmaker_cli.invariants import expect, expect_present


def test_expect_passes_a_held_invariant():
    expect(True, "never raised")


def test_expect_raises_the_broken_invariant():
    with pytest.raises(RuntimeError, match="the sky fell"):
        expect(False, "the sky fell")


@pytest.mark.parametrize("value", [0, "", [], "song"])
def test_expect_present_returns_any_value_but_none(value):
    assert expect_present(value, "never raised") == value


def test_expect_present_raises_the_broken_invariant_for_none():
    with pytest.raises(RuntimeError, match="no song"):
        expect_present(None, "no song")
