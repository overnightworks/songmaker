"""Tests for the diffusion-step progress text parser."""

from __future__ import annotations

from acestep_worker.progress import parse_step_fraction


def test_parse_step_fraction_basic() -> None:
    assert parse_step_fraction("8/50 [00:02<00:13]") == 8 / 50


def test_parse_step_fraction_complete() -> None:
    assert parse_step_fraction("50/50 [00:13<00:00]") == 1.0


def test_parse_step_fraction_caps_at_one() -> None:
    assert parse_step_fraction("60/50 [00:13<00:00]") == 1.0


def test_parse_step_fraction_zero_total_returns_none() -> None:
    assert parse_step_fraction("8/0 [00:02<00:13]") is None


def test_parse_step_fraction_no_bracket_returns_none() -> None:
    assert parse_step_fraction("LM chunk 1/1") is None


def test_parse_step_fraction_no_match_returns_none() -> None:
    assert parse_step_fraction("Loading model...") is None


def test_parse_step_fraction_empty_returns_none() -> None:
    assert parse_step_fraction("") is None
