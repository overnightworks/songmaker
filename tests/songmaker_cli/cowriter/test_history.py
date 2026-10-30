"""Token-budgeted co-writer history (#26)."""

from __future__ import annotations

from types import SimpleNamespace

from songmaker_cli.cowriter.history import (
    compact_conversation,
    count_tokens,
    fold_summary,
)


def _msg(i: int, text: str, role: str = "user"):
    return SimpleNamespace(id=f"m{i}", role=role, content=text)


def test_under_budget_stays_verbatim():
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
