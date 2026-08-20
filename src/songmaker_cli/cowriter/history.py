"""Token-budgeted conversation history for every co-writer provider."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from songmaker_cli.constants import COWRITER_SUMMARY_TAG
from songmaker_cli.db.models import ChatMessage, ConversationSummary

Summarizer = Callable[[str | None, Sequence[ChatMessage]], str]


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True)
class CompactedHistory:
    summary_text: str | None
    tail: tuple[ChatMessage, ...]
    last_summarized_message_id: str | None
    windowed: bool

    def to_api_messages(self) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if self.summary_text:
            messages.append({
                "role": "user",
                "content": (
                    f"<{COWRITER_SUMMARY_TAG}>\n"
                    f"{self.summary_text}\n"
                    f"</{COWRITER_SUMMARY_TAG}>"
                ),
            })
        messages.extend(
            {"role": msg.role, "content": msg.content} for msg in self.tail
        )
        return messages


def _message_tokens(messages: Sequence[ChatMessage]) -> int:
    return sum(count_tokens(msg.content) for msg in messages)


def _newest_fitting_tail(
    messages: Sequence[ChatMessage], budget: int,
) -> list[ChatMessage]:
    if not messages:
        return []
    selected: list[ChatMessage] = []
    tokens = 0
    for msg in reversed(messages):
        cost = count_tokens(msg.content)
        if selected and tokens + cost > budget:
            break
        selected.append(msg)
        tokens += cost
    selected.reverse()
    return selected


def compact_conversation(
    messages: Sequence[ChatMessage],
    *,
    budget: int,
    existing: ConversationSummary | None = None,
    summarize: Summarizer | None = None,
) -> CompactedHistory:
    """Cover every historical message once: optional summary plus a token tail.

    Under budget the conversation stays verbatim. Over budget, older
    messages are folded into a rolling summary. A summarizer failure
    keeps a limited tail and never falls back to full history.
    """
    ordered = list(messages)
    if _message_tokens(ordered) <= budget:
        return CompactedHistory(
            summary_text=None,
            tail=tuple(ordered),
            last_summarized_message_id=(
                existing.last_summarized_message_id if existing else None
            ),
            windowed=False,
        )

    already_summarized_id = (
        existing.last_summarized_message_id if existing else None
    )
    if already_summarized_id:
        prefix_done = []
        remainder = []
        seen_boundary = False
        for msg in ordered:
            if not seen_boundary:
                prefix_done.append(msg)
                if msg.id == already_summarized_id:
                    seen_boundary = True
                continue
            remainder.append(msg)
        if not seen_boundary:
            remainder = ordered
            prefix_done = []
            already_summarized_id = None
    else:
        prefix_done = []
        remainder = ordered

    tail = _newest_fitting_tail(remainder, budget)
    to_fold = remainder[: len(remainder) - len(tail)] if tail else remainder
    if not to_fold and existing and existing.summary_text:
        return CompactedHistory(
            summary_text=existing.summary_text,
            tail=tuple(tail),
            last_summarized_message_id=already_summarized_id,
            windowed=True,
        )

    previous = existing.summary_text if existing else None
    if summarize is None:
        return CompactedHistory(
            summary_text=previous,
            tail=tuple(tail),
            last_summarized_message_id=already_summarized_id,
            windowed=True,
        )
    try:
        summary = summarize(previous, to_fold)
    except Exception:
        return CompactedHistory(
            summary_text=previous,
            tail=tuple(tail),
            last_summarized_message_id=already_summarized_id,
            windowed=True,
        )
    last_id = to_fold[-1].id if to_fold else already_summarized_id
    return CompactedHistory(
        summary_text=summary,
        tail=tuple(tail),
        last_summarized_message_id=last_id,
        windowed=True,
    )


def fold_summary(
    previous: str | None, new_messages: Sequence[ChatMessage],
) -> str:
    """Deterministic rolling summary used when no model summarizer is injected."""
    from songmaker_cli.constants import COWRITER_MAX_SUMMARY_CHARS

    parts: list[str] = []
    if previous:
        parts.append(previous.strip())
    for msg in new_messages:
        parts.append(f"{msg.role}: {msg.content.strip()}")
    folded = "\n".join(part for part in parts if part)
    if len(folded) <= COWRITER_MAX_SUMMARY_CHARS:
        return folded
    return folded[-COWRITER_MAX_SUMMARY_CHARS:]
