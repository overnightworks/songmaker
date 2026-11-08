"""Token-budgeted co-writer history (#26)."""

from __future__ import annotations

from types import SimpleNamespace

from songmaker_cli.constants import COWRITER_MAX_SUMMARY_CHARS, COWRITER_SUMMARY_TAG
from songmaker_cli.cowriter.history import (
    compact_conversation,
    count_tokens,
    fold_summary,
)


def _msg(i: int, text: str, role: str = "user"):
    return SimpleNamespace(id=f"m{i}", role=role, content=text)


def test_under_budget_stays_verbatim():
    """Spec: REQ-COWRITER-05 -- history within the token budget is rendered message for
    message."""
    messages = [_msg(1, "hello"), _msg(2, "world")]
    compacted = compact_conversation(
        messages, budget=10_000, summarize=fold_summary,
    )
    assert compacted.windowed is False
    assert compacted.summary_text is None
    assert [m.id for m in compacted.tail] == ["m1", "m2"]
    rendered = compacted.to_api_messages()
    assert [m["content"] for m in rendered] == ["hello", "world"]


def test_over_budget_uses_summary_plus_token_tail_not_message_count():
    # 20 tokens each if count is (len+3)//4. "xxxx"*20 = 80 chars -> 20 tokens.
    chunk = "x" * 80
    messages = [_msg(i, f"{chunk}-{i}") for i in range(10)]
    compacted = compact_conversation(
        messages, budget=50, summarize=fold_summary,
    )
    assert compacted.windowed is True
    assert compacted.summary_text is not None
    tail_tokens = sum(count_tokens(m.content) for m in compacted.tail)
    assert tail_tokens <= 50
    ids = [m.id for m in compacted.tail]
    folded_ids = [m.id for m in messages if m.id not in ids]
    assert folded_ids
    assert compacted.last_summarized_message_id == folded_ids[-1]
    for msg in messages:
        in_summary = msg.content in compacted.summary_text
        in_tail = msg.id in ids
        assert in_summary ^ in_tail


def test_smaller_budget_shrinks_verbatim_tail():
    chunk = "x" * 80
    messages = [_msg(i, f"{chunk}-{i}") for i in range(10)]
    wide = compact_conversation(messages, budget=80, summarize=fold_summary)
    narrow = compact_conversation(messages, budget=40, summarize=fold_summary)
    assert len(narrow.tail) < len(wide.tail)


def test_incremental_update_does_not_overlap_or_drop():
    chunk = "x" * 80
    first = [_msg(i, f"{chunk}-{i}") for i in range(6)]
    first_pass = compact_conversation(first, budget=40, summarize=fold_summary)
    extra = first + [_msg(i, f"{chunk}-{i}") for i in range(6, 10)]
    existing = SimpleNamespace(
        summary_text=first_pass.summary_text,
        last_summarized_message_id=first_pass.last_summarized_message_id,
    )
    second = compact_conversation(
        extra, budget=40, existing=existing, summarize=fold_summary,
    )
    covered = set()
    if second.summary_text:
        for msg in extra:
            if msg.content in second.summary_text:
                covered.add(msg.id)
    covered.update(m.id for m in second.tail)
    assert covered == {m.id for m in extra}


def test_summarizer_failure_keeps_limited_tail_not_full_history():
    """Spec: REQ-COWRITER-07 -- a failing summarizer leaves a summary-less turn with a tail
    that is shorter than the history and within budget."""
    chunk = "x" * 80
    messages = [_msg(i, f"{chunk}-{i}") for i in range(8)]

    def _boom(_prev, _msgs):
        raise RuntimeError("summarizer down")

    compacted = compact_conversation(
        messages, budget=40, summarize=_boom,
    )
    assert compacted.windowed is True
    assert compacted.summary_text is None
    assert len(compacted.tail) < len(messages)
    assert sum(count_tokens(m.content) for m in compacted.tail) <= 40


def _existing(summary_text: str, last_id: str):
    return SimpleNamespace(summary_text=summary_text, last_summarized_message_id=last_id)


def test_compacted_history_renders_summary_first_in_tag_then_tail():
    messages = [_msg(i, "x" * 80) for i in range(6)]
    compacted = compact_conversation(
        messages, budget=40, summarize=lambda _prev, _msgs: "earlier talk",
    )
    rendered = compacted.to_api_messages()
    assert rendered[0] == {
        "role": "user",
        "content": f"<{COWRITER_SUMMARY_TAG}>\nearlier talk\n</{COWRITER_SUMMARY_TAG}>",
    }
    assert [m["content"] for m in rendered[1:]] == [m.content for m in compacted.tail]


def test_existing_summary_with_fitting_remainder_keeps_summary_and_boundary():
    messages = [_msg(i, "x" * 80) for i in range(6)]
    existing = _existing("earlier talk", "m3")
    compacted = compact_conversation(
        messages, budget=50, existing=existing, summarize=lambda _prev, _msgs: "rewritten",
    )
    assert compacted.summary_text == "earlier talk"
    assert compacted.last_summarized_message_id == "m3"
    assert [m.id for m in compacted.tail] == ["m4", "m5"]
    assert compacted.windowed is True


def test_missing_boundary_message_counts_every_message_as_unsummarized():
    messages = [_msg(i, "x" * 80) for i in range(6)]
    folded: list[list[str]] = []

    def _record(_prev, to_fold):
        folded.append([m.id for m in to_fold])
        return "new summary"

    compacted = compact_conversation(
        messages, budget=40, existing=_existing("old", "gone"), summarize=_record,
    )
    assert folded == [["m0", "m1", "m2", "m3"]]
    assert compacted.last_summarized_message_id == "m3"


def test_fold_summary_past_its_cap_keeps_the_newest_characters():
    text = "y" * (COWRITER_MAX_SUMMARY_CHARS + 500) + "newest"
    summary = fold_summary(None, [_msg(1, text)])
    assert len(summary) == COWRITER_MAX_SUMMARY_CHARS
    assert summary.endswith("newest")
