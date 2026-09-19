"""Observable audit behavior, without model imports, downloads or provider calls."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import similar_functions as audit  # noqa: E402

SOURCE = '''\
def choose(value: int) -> int:
    """Choose an adjusted value."""
    if value > 0:
        return value + 1
    return 0
'''


class FakeEmbedder:
    def __init__(self):
        self.texts = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [(3.0, 4.0) for _ in texts]


class FakeSummarizer:
    def __init__(self):
        self.texts = []

    def summarize(self, text):
        self.texts.append(text)
        return "Given a number, decides its adjusted value."


class UnavailablePort:
    def embed(self, texts):
        pytest.fail("A warm cache must not call the embedding model")

    def summarize(self, text):
        pytest.fail("A warm cache must not call Claude")


@pytest.fixture(autouse=True)
def _no_live_provider_credentials(monkeypatch):
    """Provider-boundary tests must not inherit a developer's API credentials."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def functions():
    first = audit.extract_functions(SOURCE, Path("src/one.py"))[0]
    return [first, replace(first, path=Path("src/two.py"))]


def test_extracts_async_methods_nested_functions_and_signatures():
    source = '''\
class Judge:
    async def choose(self, value: int, *, limit=2) -> int:
        """Choose a value."""
        def adjust(value):
            if value < 0:
                return 0
            return value
        result = adjust(value)
        return min(result, limit)
'''
    outer, inner = audit.extract_functions(source, Path("judge.py"))
    assert outer.name == "Judge.choose"
    assert outer.line == 2
    assert outer.signature == "async def Judge.choose(self, value: int, *, limit=2) -> int"
    assert outer.docstring == "Choose a value."
    assert outer.body.startswith("def adjust(value):")
    assert inner.name == "Judge.choose.adjust"


@pytest.mark.parametrize(
    "source",
    [
        "def short():\n    return 1\n",
        "def documented():\n    '''Long\n    documentation\n    here.'''; return 1\n",
        "def __init__(self):\n    self.a = 1\n    self.b = 2\n    self.c = 3\n",
        "def delegate(a):\n    return other(\n        a,\n        True,\n    )\n",
        "async def delegate(a):\n    return await other(a)\n",
    ],
)
def test_excludes_initializers_short_bodies_and_delegation(source):
    assert audit.extract_functions(source, Path("module.py")) == []


def test_format_and_comments_do_not_invalidate_content_hash(functions):
    changed = SOURCE.replace("value > 0", "value>0").replace("return 0", "return 0  # zero")
    other = audit.extract_functions(changed, Path("elsewhere.py"))[0]
    assert other.key == functions[0].key
    assert other.text == functions[0].text
    behavioral = audit.extract_functions(SOURCE.replace("+ 1", "+ 2"), Path("one.py"))[0]
    assert behavioral.key != other.key


def test_discovery_deduplicates_roots_and_only_includes_tests_when_requested(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for directory in ("src", "tests"):
        (tmp_path / directory).mkdir()
        (
            tmp_path / directory / "test_case.py"
            if directory == "tests"
            else tmp_path / directory / "one.py"
        ).write_text(SOURCE)
    paths = [Path("src"), Path("src/one.py"), Path("tests")]
    assert len(audit.discover_functions(paths)) == 1
    assert len(audit.discover_functions([Path("src")], include_tests=True)) == 2
    with pytest.raises(audit.AuditError, match="does not exist"):
        audit.discover_functions([Path("absent")])


def test_cache_reuses_identical_content_and_only_recomputes_changes(tmp_path, functions):
    cache = audit.Cache(tmp_path)
    embedder, summarizer = FakeEmbedder(), FakeSummarizer()
    first = audit.collect_signals(functions, embedder, summarizer, cache, "code", "claude")
    assert len(embedder.texts) == 2
    assert len(summarizer.texts) == 1
    warm = audit.collect_signals(
        functions, UnavailablePort(), UnavailablePort(), cache, "code", "claude"
    )
    assert warm == first
    changed = audit.extract_functions(SOURCE.replace("+ 1", "+ 2"), Path("three.py"))[0]
    audit.collect_signals([*functions, changed], embedder, summarizer, cache, "code", "claude")
    assert len(embedder.texts) == 4
    assert len(summarizer.texts) == 2


def test_changing_embedding_model_preserves_summaries_but_refreshes_vectors(tmp_path, functions):
    cache = audit.Cache(tmp_path)
    audit.collect_signals(functions, FakeEmbedder(), FakeSummarizer(), cache, "old", "claude")
    embedder = FakeEmbedder()
    audit.collect_signals(functions, embedder, UnavailablePort(), cache, "new", "claude")
    assert len(embedder.texts) == 2


def test_enabling_summaries_or_changing_summary_model_reuses_code(tmp_path, functions):
    cache = audit.Cache(tmp_path)
    audit.collect_signals(functions, FakeEmbedder(), None, cache, "code", "claude")
    for model in ("claude", "other-claude"):
        embedder, summarizer = FakeEmbedder(), FakeSummarizer()
        result = audit.collect_signals(functions, embedder, summarizer, cache, "code", model)
        assert embedder.texts == [result[0].summary]
        assert len(summarizer.texts) == 1


@pytest.mark.parametrize("vector", [[], [0, 0], [float("nan")], [float("inf")], ["x"]])
def test_rejects_invalid_model_vectors(vector):
    with pytest.raises(audit.AuditError, match="Embedding"):
        audit.unit_vector(vector)


def test_corrupt_cache_fails_loudly(tmp_path, functions):
    cache = audit.Cache(tmp_path)
    path = cache.path("code-v1:code", functions[0].key)
    path.parent.mkdir()
    path.write_text("{broken")
    with pytest.raises(audit.AuditError, match="Cannot read cache"):
        audit.collect_signals(functions, UnavailablePort(), None, cache, "code", "claude")


def test_embedding_port_must_return_one_consistent_vector_per_text(tmp_path):
    class BadEmbedder:
        def embed(self, texts):
            return []

    with pytest.raises(audit.AuditError, match="number of vectors"):
        audit.cached_vectors({"one": "text"}, BadEmbedder(), audit.Cache(tmp_path), "model")
    cache = audit.Cache(tmp_path)
    cache.write("model", "one", [1, 0])
    cache.write("model", "two", [1, 0, 0])
    with pytest.raises(audit.AuditError, match="dimensions"):
        audit.cached_vectors({"one": "a", "two": "b"}, UnavailablePort(), cache, "model")


def test_empty_summary_fails_without_caching_success(tmp_path, functions):
    class EmptySummarizer:
        def summarize(self, text):
            return "\n  "

    with pytest.raises(audit.AuditError, match="empty summary"):
        audit.collect_signals(
            functions, FakeEmbedder(), EmptySummarizer(), audit.Cache(tmp_path), "code", "claude"
        )


def test_pairs_support_either_or_both_signals_and_sort_by_mean(functions):
    first, second = functions
    third = replace(first, path=Path("three.py"))
    signals = [
        audit.FunctionSignals(first, (1, 0), "a", (1, 0)),
        audit.FunctionSignals(second, (1, 0), "b", (0, 1)),
        audit.FunctionSignals(third, (0.8, 0.6), "c", (1, 0)),
    ]
    pairs = audit.find_pairs(signals, 0.9, 0.9)
    assert [(p.code_score, p.summary_score, p.score) for p in pairs] == [
        (0.8, 1, 0.9),
        (1, 0, 0.5),
    ]
    assert audit.find_pairs(signals, 0.9, 0.9, require_both=True) == []
    assert len(audit.find_pairs(signals, 0.8, 0.9, require_both=True)) == 1


def test_pairs_exclude_self_but_keep_distinct_identical_functions(functions):
    first, second = functions
    signals = [audit.FunctionSignals(first, (1, 0)), audit.FunctionSignals(second, (1, 0))]
    assert len(audit.find_pairs(signals, 1)) == 1
    assert audit.find_pairs([signals[0], signals[0]]) == []


def test_report_contains_locations_signatures_separate_scores_and_escaped_summaries(functions):
    signals = [
        audit.FunctionSignals(f, (1, 0), "Checks `x | y` < z.\nThen decides.", (1, 0))
        for f in functions
    ]
    report = audit.render_report(audit.find_pairs(signals), 2, "code", "claude", 0.9, 0.9, False)
    assert "src/one.py:1" in report and "src/two.py:1" in report
    assert "def choose(value: int) -&gt; int" in report
    assert "| 1.0000 | 1.0000 | 1.0000 |" in report
    assert "&#96;x &#124; y&#96; &lt; z. Then decides." in report
    assert all(len(line.split("|")) == 9 for line in report.splitlines() if line.startswith("|"))


@pytest.mark.parametrize(("limit", "status"), [("0.99", 1), ("1", 0)])
def test_cli_warm_cache_report_and_ratchet_need_no_ports(tmp_path, monkeypatch, limit, status):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "src"
    source.mkdir()
    for filename in ("a.py", "b.py"):
        (source / filename).write_text(SOURCE)
    cache = audit.Cache(tmp_path / "cache")
    audit.collect_signals(
        audit.discover_functions([source]),
        FakeEmbedder(),
        None,
        cache,
        audit.DEFAULT_MODEL,
        audit.DEFAULT_CLAUDE_MODEL,
    )
    report = tmp_path / "report.md"
    assert (
        audit.main(
            [
                str(source),
                "--no-summaries",
                "--cache-dir",
                str(cache.root),
                "--report",
                str(report),
                "--fail-above",
                limit,
            ]
        )
        == status
    )
    assert "Summaries: disabled (--no-summaries)" in report.read_text()
    assert "matching pairs: 1" in report.read_text()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--code-threshold", "nan"],
        ["--summary-threshold", "2"],
        ["--fail-above", "inf"],
        ["--summary-workers", "0"],
        ["--no-summaries", "--require-both"],
    ],
)
def test_cli_rejects_invalid_options(arguments):
    with pytest.raises(SystemExit) as error:
        audit.main(arguments)
    assert error.value.code == 2


def test_missing_claude_is_a_named_failure(monkeypatch):
    monkeypatch.setattr(audit.shutil, "which", lambda command: None)
    with pytest.raises(audit.AuditError, match="Claude CLI unavailable"):
        audit.ClaudeSummarizer("model").summarize(SOURCE)


def test_claude_receives_source_as_stdin_without_tools_or_project_settings(monkeypatch):
    monkeypatch.setattr(audit.shutil, "which", lambda command: "/bin/claude")

    def invoke(command, **kwargs):
        assert command[:4] == ["/bin/claude", "-p", "--model", "configured-model"]
        assert command[command.index("--tools") + 1] == ""
        assert command[command.index("--setting-sources") + 1] == ""
        assert "--strict-mcp-config" in command
        assert "--disable-slash-commands" in command
        assert kwargs["input"] == audit.SUMMARY_PROMPT + SOURCE
        return subprocess.CompletedProcess(command, 0, "Chooses a value.\n")

    monkeypatch.setattr(audit.subprocess, "run", invoke)
    assert audit.ClaudeSummarizer("configured-model").summarize(SOURCE) == "Chooses a value."


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_claude_failure_is_named_without_echoing_provider_output(monkeypatch, failure):
    monkeypatch.setattr(audit.shutil, "which", lambda command: "/bin/claude")

    def invoke(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 120)
        return subprocess.CompletedProcess(command, 1, "private provider output")

    monkeypatch.setattr(audit.subprocess, "run", invoke)
    with pytest.raises(audit.AuditError, match="Claude summary") as error:
        audit.ClaudeSummarizer("model").summarize(SOURCE)
    assert "private provider output" not in str(error.value)


def test_summary_failure_stops_before_dispatching_remaining_batches(tmp_path):
    functions = [
        audit.extract_functions(SOURCE.replace("+ 1", f"+ {n}"), Path(f"{n}.py"))[0]
        for n in range(4)
    ]

    class FailingSummarizer:
        def summarize(self, text):
            if text != functions[0].text:
                pytest.fail("Failed summaries must not dispatch the remaining work")
            raise audit.AuditError("Claude unavailable")

    with pytest.raises(audit.AuditError, match="Claude unavailable"):
        audit.collect_signals(
            functions,
            FakeEmbedder(),
            FailingSummarizer(),
            audit.Cache(tmp_path),
            "model",
            "claude",
            summary_workers=1,
        )


def test_cli_empty_source_needs_no_model_and_reports_zero_pairs(tmp_path, capsys):
    assert audit.main([str(tmp_path)]) == 0
    assert "Functions: 0; matching pairs: 0" in capsys.readouterr().out


def test_cli_missing_input_is_a_named_error(tmp_path, capsys):
    assert audit.main([str(tmp_path / "absent")]) == 2
    assert "Source path does not exist" in capsys.readouterr().err


def test_generic_signature_keeps_type_parameters():
    source = SOURCE.replace("choose(value: int) -> int", "choose[T](value: T) -> T")
    function = audit.extract_functions(source, Path("generic.py"))[0]
    assert function.signature == "def choose[T](value: T) -> T"


@pytest.mark.parametrize("api_fails", [False, True])
def test_configured_api_uses_model_or_reports_provider_failure(monkeypatch, api_fails):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "test-placeholder"
            assert kwargs["max_retries"] == 0
            self.messages = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def create(self, **kwargs):
            assert kwargs["model"] == "configured-model"
            assert kwargs["messages"] == [
                {"role": "user", "content": audit.SUMMARY_PROMPT + SOURCE}
            ]
            if api_fails:
                raise OSError("private provider output")
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Chooses a value.")])

    monkeypatch.setitem(
        sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeClient, APIError=OSError)
    )
    if api_fails:
        with pytest.raises(audit.AuditError, match="Claude summary API failed") as error:
            audit.ClaudeSummarizer("configured-model").summarize(SOURCE)
        assert "private provider output" not in str(error.value)
    else:
        assert audit.ClaudeSummarizer("configured-model").summarize(SOURCE) == "Chooses a value."


def test_configured_api_without_sdk_fails_instead_of_switching_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(audit.AuditError, match="SDK is missing"):
        audit.ClaudeSummarizer("model").summarize(SOURCE)


def test_summary_limit_aborts_before_any_model_call(tmp_path, functions, capsys):
    changed = replace(functions[0], text="different content")
    with pytest.raises(audit.AuditError, match="2 missing summaries.*--no-summaries"):
        audit.collect_signals(
            [*functions, changed],
            UnavailablePort(),
            UnavailablePort(),
            audit.Cache(tmp_path),
            "code",
            "claude",
            max_summaries=1,
        )
    assert "Summary cache misses: 2" in capsys.readouterr().err


def test_summary_limit_counts_only_unique_misses_and_allows_exact_limit(
    tmp_path, functions, capsys
):
    cache = audit.Cache(tmp_path)
    audit.collect_signals(
        functions, FakeEmbedder(), FakeSummarizer(), cache, "code", "claude", max_summaries=1
    )
    assert "Summary cache misses: 1" in capsys.readouterr().err
    changed = replace(functions[0], text="different content")
    audit.collect_signals(
        [*functions, changed],
        FakeEmbedder(),
        FakeSummarizer(),
        cache,
        "code",
        "claude",
        max_summaries=1,
    )
    assert "Summary cache misses: 1" in capsys.readouterr().err
    audit.collect_signals(
        [*functions, changed],
        UnavailablePort(),
        UnavailablePort(),
        cache,
        "code",
        "claude",
        max_summaries=1,
    )
    assert "Summary cache misses: 0" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "path", "expected"),
    [
        ("Judge.choose.adjust", "src/one.py", 0),
        ("Judge.choose.adjust", "src/two.py", 1),
        ("Judge.chooser", "src/one.py", 1),
    ],
)
def test_pairs_skip_only_enclosing_functions_in_same_file(functions, name, path, expected):
    outer = replace(functions[0], name="Judge.choose")
    other = replace(outer, name=name, path=Path(path), line=10)
    signals = [audit.FunctionSignals(f, (1, 0)) for f in (outer, other)]
    assert len(audit.find_pairs(signals)) == expected
    assert len(audit.find_pairs(signals[::-1])) == expected


@pytest.mark.parametrize("model", [audit.DEFAULT_MODEL, "other-model"])
def test_embedding_loader_pins_default_weights_and_external_code(monkeypatch, model):
    def load(name, **kwargs):
        assert name == model
        is_default = model == audit.DEFAULT_MODEL
        assert kwargs["trust_remote_code"] is is_default
        assert kwargs["revision"] == (audit.DEFAULT_MODEL_REVISION if is_default else None)
        for key in ("model_kwargs", "config_kwargs"):
            assert kwargs[key] == (
                {"code_revision": audit.DEFAULT_MODEL_CODE_REVISION} if is_default else {}
            )
        return SimpleNamespace(
            encode=lambda *args, **kwargs: SimpleNamespace(tolist=lambda: [[1, 0]])
        )

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda count: None))
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=load)
    )
    assert audit.LocalEmbedder(model).embed(["code"]) == [[1, 0]]


def test_cli_applies_summary_limit_before_calling_ports(tmp_path, capsys):
    (tmp_path / "source.py").write_text(
        SOURCE + SOURCE.replace("choose", "other").replace("+ 1", "+ 2")
    )
    assert (
        audit.main([str(tmp_path), "--cache-dir", str(tmp_path / "cache"), "--max-summaries", "1"])
        == 2
    )
    assert "2 missing summaries exceed --max-summaries 1" in capsys.readouterr().err
