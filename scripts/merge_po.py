"""Git merge driver that merges a gettext PO catalog entry by entry.

Registered by ``scripts/setup_git.sh`` as ``python3 scripts/merge_po.py %O %A %B``: ancestor,
ours, theirs. The merged catalog replaces ours. An entry is a blank-line separated block
(its comments, ``msgctxt``, ``msgid``, ``msgid_plural``, ``msgstr`` lines) identified by its
``msgctxt`` and ``msgid``; a key repeated inside one input stops the driver. An entry changed
or added on either side is kept; one is dropped only where one side deleted it and the other
left it unchanged. An entry with different texts on the two sides, or a ``msgctxt`` with
different new ``msgid`` texts on the two sides, is written between conflict markers and the
exit status is 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

EntryKey = tuple[str, str]
CONFLICT_OURS = "<<<<<<< ours"
CONFLICT_SEPARATOR = "======="
CONFLICT_THEIRS = ">>>>>>> theirs"
IDENTITY_FIELDS = ("msgctxt", "msgid")
FIELDS = ("msgctxt", "msgid_plural", "msgid", "msgstr")


def split_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def entry_key(block: str) -> EntryKey:
    parts = dict.fromkeys(IDENTITY_FIELDS, "")
    current_field = ""
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith('"'):
            if current_field in parts:
                parts[current_field] += stripped
            continue
        current_field = next(
            (field for field in FIELDS if stripped.startswith((f"{field} ", f"{field}["))), ""
        )
        if current_field in parts:
            parts[current_field] += stripped[len(current_field) :].strip()
    if not parts["msgid"]:
        raise SystemExit(f"merge_po: block without a msgid: {block.splitlines()[0]!r}")
    return parts["msgctxt"], parts["msgid"]


def parse_catalog(text: str) -> dict[EntryKey, str]:
    entries: dict[EntryKey, str] = {}
    for block in split_blocks(text):
        key = entry_key(block)
        if key in entries:
            raise SystemExit(f"merge_po: repeated entry in one input: {key[0]!r} / {key[1]!r}")
        entries[key] = block
    return entries


def reworded_contexts(
    base: dict[EntryKey, str], ours: dict[EntryKey, str], theirs: dict[EntryKey, str]
) -> set[str]:
    """Contexts where each side has an entry new against base, with different msgids."""

    def new_msgids(side: dict[EntryKey, str]) -> dict[str, set[str]]:
        by_context: dict[str, set[str]] = {}
        for context, msgid in side.keys():
            if context and (context, msgid) not in base:
                by_context.setdefault(context, set()).add(msgid)
        return by_context

    our_new, their_new = new_msgids(ours), new_msgids(theirs)
    return {
        context
        for context, our_msgids in our_new.items()
        if context in their_new and our_msgids != their_new[context]
    }


def context_blocks(catalog: dict[EntryKey, str], context: str) -> str:
    return "\n\n".join(
        block for (block_context, _), block in catalog.items() if block_context == context
    )


def conflict_block(ours: str | None, theirs: str | None) -> str:
    return "\n".join([CONFLICT_OURS, ours or "", CONFLICT_SEPARATOR, theirs or "", CONFLICT_THEIRS])


def merge_order(
    base: dict[EntryKey, str], ours: dict[EntryKey, str], theirs: dict[EntryKey, str]
) -> list[EntryKey]:
    """Our order, with each entry only theirs has placed after its predecessor in theirs."""
    order = list(ours)
    seen = set(order)
    anchor: EntryKey | None = None
    for key in theirs:
        if key in seen:
            anchor = key
            continue
        position = 0 if anchor is None else order.index(anchor) + 1
        # Entries only ours added sit after the anchor too; ours stays first.
        while (
            position < len(order) and order[position] not in base and order[position] not in theirs
        ):
            position += 1
        order.insert(position, key)
        seen.add(key)
        anchor = key
    for key in base:
        if key not in seen:
            order.append(key)
    return order


def merge_catalogs(base_text: str, ours_text: str, theirs_text: str) -> tuple[str, bool]:
    base = parse_catalog(base_text)
    ours = parse_catalog(ours_text)
    theirs = parse_catalog(theirs_text)
    blocks: list[str] = []
    conflicted = False
    rewordings = reworded_contexts(base, ours, theirs)
    reported: set[str] = set()
    for key in merge_order(base, ours, theirs):
        context = key[0]
        if context in rewordings:
            if context not in reported:
                reported.add(context)
                blocks.append(
                    conflict_block(context_blocks(ours, context), context_blocks(theirs, context))
                )
                conflicted = True
            continue
        base_block, our_block, their_block = base.get(key), ours.get(key), theirs.get(key)
        if our_block == their_block or their_block == base_block:
            chosen = our_block
        elif our_block == base_block:
            chosen = their_block
        else:
            blocks.append(conflict_block(our_block, their_block))
            conflicted = True
            continue
        if chosen is not None:
            blocks.append(chosen)
    return "\n\n".join(blocks) + "\n", conflicted


def merge_file_path(argument: str) -> Path:
    resolved = Path(argument).resolve()
    if not resolved.is_relative_to(Path.cwd().resolve()):
        raise SystemExit(f"merge file outside the working tree: {argument}")
    return resolved


def main(argv: list[str]) -> int:
    base_path, ours_path, theirs_path = (merge_file_path(argument) for argument in argv[1:4])
    merged, conflicted = merge_catalogs(
        base_path.read_text(encoding="utf-8"),
        ours_path.read_text(encoding="utf-8"),
        theirs_path.read_text(encoding="utf-8"),
    )
    ours_path.write_text(merged, encoding="utf-8")
    return 1 if conflicted else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
