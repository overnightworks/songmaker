"""Tests for ``scripts/merge_po.py``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import merge_po  # noqa: E402

HEADER = 'msgid ""\nmsgstr ""\n"Language: en\\n"'


def entry(name: str, translation: str = "") -> str:
    return f'msgctxt "{name}"\nmsgid "Source of {name}"\nmsgstr "{translation}"'


def catalog(*entries: str) -> str:
    return "\n\n".join([HEADER, *entries]) + "\n"


@pytest.fixture(autouse=True)
def working_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def merge_files(tmp_path: Path, base: str, ours: str, theirs: str) -> tuple[int, str]:
    paths = []
    for name, content in (("base", base), ("ours", ours), ("theirs", theirs)):
        path = tmp_path / f"{name}.po"
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    status = merge_po.main(["merge_po.py", *(str(path) for path in paths)])
    return status, paths[1].read_text(encoding="utf-8")


def test_both_sides_new_entries_are_kept_whole(tmp_path: Path) -> None:
    base = catalog(entry("a"))
    ours = catalog(entry("a"), entry("ours.new"))
    theirs = catalog(entry("a"), entry("theirs.new"))

    status, merged = merge_files(tmp_path, base, ours, theirs)

    assert status == 0
    assert merged == catalog(entry("a"), entry("ours.new"), entry("theirs.new"))


def test_entry_inserted_in_the_middle_keeps_its_place(tmp_path: Path) -> None:
    base = catalog(entry("a"), entry("c"))
    ours = catalog(entry("a"), entry("c"), entry("d"))
    theirs = catalog(entry("a"), entry("b"), entry("c"))

    _, merged = merge_files(tmp_path, base, ours, theirs)

    assert merged == catalog(entry("a"), entry("b"), entry("c"), entry("d"))


def test_one_sided_deletion_goes(tmp_path: Path) -> None:
    base = catalog(entry("a"), entry("b"))
    ours = catalog(entry("a"))
    theirs = catalog(entry("a"), entry("b"), entry("t"))

    status, merged = merge_files(tmp_path, base, ours, theirs)

    assert status == 0
    assert merged == catalog(entry("a"), entry("t"))


def test_one_sided_change_wins_over_unchanged_side(tmp_path: Path) -> None:
    base = catalog(entry("a"))
    theirs = catalog(entry("a", "Better"))

    status, merged = merge_files(tmp_path, base, base, theirs)

    assert status == 0
    assert merged == theirs


def test_comments_plurals_and_multiline_strings_stay_with_their_entry(tmp_path: Path) -> None:
    plural = (
        '#. Shown in the list\nmsgctxt "songCount"\nmsgid "{count} song"\n'
        'msgid_plural "{count} songs"\nmsgstr[0] ""\nmsgstr[1] ""'
    )
    long_entry = 'msgctxt "long"\nmsgid ""\n"First line "\n"second line"\nmsgstr ""'
    base = catalog(entry("a"))

    status, merged = merge_files(
        tmp_path, base, catalog(entry("a"), plural), catalog(entry("a"), long_entry)
    )

    assert status == 0
    assert merged == catalog(entry("a"), plural, long_entry)


def test_same_entry_with_different_text_conflicts(tmp_path: Path) -> None:
    base = catalog(entry("a"))
    ours = catalog(entry("a", "Ours"))
    theirs = catalog(entry("a", "Theirs"))

    status, merged = merge_files(tmp_path, base, ours, theirs)

    assert status == 1
    assert merge_po.CONFLICT_OURS in merged
    assert 'msgstr "Ours"' in merged
    assert 'msgstr "Theirs"' in merged


@pytest.mark.parametrize("deleting_side", ["ours", "theirs"])
def test_deletion_against_a_change_conflicts(tmp_path: Path, deleting_side: str) -> None:
    base = catalog(entry("a"))
    deleted = catalog()
    changed = catalog(entry("a", "Changed"))
    ours, theirs = (deleted, changed) if deleting_side == "ours" else (changed, deleted)

    status, _ = merge_files(tmp_path, base, ours, theirs)

    assert status == 1


def test_a_merge_file_outside_the_working_tree_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    outside = tmp_path / "outside.po"
    outside.write_text(catalog(), encoding="utf-8")
    monkeypatch.chdir(tree)

    with pytest.raises(SystemExit):
        merge_po.main(["merge_po.py", str(outside), str(outside), str(outside)])


def reworded(name: str, source: str) -> str:
    return f'msgctxt "{name}"\nmsgid "{source}"\nmsgstr ""'


def test_a_msgctxt_reworded_differently_on_both_sides_conflicts(tmp_path: Path) -> None:
    base = catalog(entry("a"))
    ours = catalog(reworded("a", "Ours wording"))
    theirs = catalog(reworded("a", "Theirs wording"))

    status, merged = merge_files(tmp_path, base, ours, theirs)

    assert status == 1
    assert merge_po.CONFLICT_OURS in merged
    assert 'msgid "Ours wording"' in merged
    assert 'msgid "Theirs wording"' in merged
    assert merged.count('msgctxt "a"') == 2


def test_a_msgctxt_reworded_the_same_way_on_both_sides_merges(tmp_path: Path) -> None:
    base = catalog(entry("a"))
    both = catalog(reworded("a", "Shared wording"))

    status, merged = merge_files(tmp_path, base, both, both)

    assert status == 0
    assert merged == both


def test_a_msgctxt_reworded_on_one_side_only_takes_the_new_wording(tmp_path: Path) -> None:
    base = catalog(entry("a"))
    theirs = catalog(reworded("a", "New wording"))

    status, merged = merge_files(tmp_path, base, base, theirs)

    assert status == 0
    assert merged == theirs


@pytest.mark.parametrize("side", ["base", "ours", "theirs"])
def test_a_repeated_key_inside_one_input_fails_loud_naming_it(tmp_path: Path, side: str) -> None:
    corrupt = catalog(entry("dup.key"), entry("dup.key", "Again"))
    clean = catalog(entry("dup.key"))
    inputs = {name: clean for name in ("base", "ours", "theirs")} | {side: corrupt}

    with pytest.raises(SystemExit, match="dup.key"):
        merge_files(tmp_path, inputs["base"], inputs["ours"], inputs["theirs"])


def test_a_comment_only_block_without_a_msgid_fails_loud(tmp_path: Path) -> None:
    corrupt = catalog("# stray comment")

    with pytest.raises(SystemExit):
        merge_files(tmp_path, catalog(), corrupt, catalog())
