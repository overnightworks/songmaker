"""Tests for ``scripts/release_layer_delta.py``."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import release_layer_delta as delta  # noqa: E402

REPOSITORY = "OvernightWorks/Songmaker"
IMAGE = "scoring-worker"
BASE_LAYERS = [("sha256:" + "a" * 64, 30_000_000), ("sha256:" + "b" * 64, 4_000_000_000)]
NEW_TOP_LAYER = ("sha256:" + "c" * 64, 60_000_000)
OLD_TOP_LAYER = ("sha256:" + "d" * 64, 50_000_000)


def _image_manifest(layers: list[tuple[str, int]]) -> dict:
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "layers": [{"digest": digest, "size": size} for digest, size in layers],
    }


def _oci_index(*platforms: tuple[str, str, str]) -> dict:
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {"digest": digest, "platform": {"os": operating_system, "architecture": architecture}}
            for digest, operating_system, architecture in platforms
        ],
    }


AMD64_DIGEST = "sha256:" + "1" * 64
ATTESTATION_DIGEST = "sha256:" + "2" * 64
RECORDED_INDEX = _oci_index(
    (ATTESTATION_DIGEST, "unknown", "unknown"),
    (AMD64_DIGEST, "linux", "amd64"),
)


def _layers(*pairs: tuple[str, int]) -> tuple[delta.Layer, ...]:
    return tuple(delta.Layer(digest=digest, size=size) for digest, size in pairs)


@pytest.mark.parametrize(
    ("refs", "version", "expected"),
    [
        pytest.param(
            ["refs/tags/v2026.11.10.3", "refs/tags/v2026.11.11.1", "refs/tags/v2026.11.9.7"],
            "2026.11.11.2",
            "2026.11.11.1",
            id="highest earlier tag",
        ),
        pytest.param(
            ["refs/tags/v2026.11.11.9", "refs/tags/v2026.11.11.10"],
            "2026.11.11.11",
            "2026.11.11.10",
            id="ten is above nine",
        ),
        pytest.param(
            ["refs/tags/v2026.11.11.1", "refs/tags/v2026.11.11.2", "refs/tags/v2026.11.12.1"],
            "2026.11.11.2",
            "2026.11.11.1",
            id="own and later tags are ignored",
        ),
        pytest.param(
            [
                "refs/tags/v1.2",
                "refs/tags/vnext",
                "refs/tags/2026.11.10.1",
                "refs/tags/v2026.11.10.1-rc",
            ],
            "2026.11.11.1",
            None,
            id="other forms are ignored",
        ),
        pytest.param([], "2026.11.11.1", None, id="no tags"),
    ],
)
def test_previous_version_is_the_highest_earlier_tag_of_the_form(refs, version, expected):
    assert delta.previous_version(refs, version) == expected


def test_amd64_layers_come_from_the_amd64_manifest_not_the_attestation():
    manifests = {
        AMD64_DIGEST: _image_manifest(BASE_LAYERS),
        ATTESTATION_DIGEST: _image_manifest([("sha256:" + "e" * 64, 1)]),
    }

    assert delta.amd64_layers(RECORDED_INDEX, manifests.__getitem__) == _layers(*BASE_LAYERS)


def test_a_plain_image_manifest_is_used_as_is():
    def refuse(_digest: str) -> dict:
        raise AssertionError("a plain manifest names no further manifest")

    assert delta.amd64_layers(_image_manifest(BASE_LAYERS), refuse) == _layers(*BASE_LAYERS)


@pytest.mark.parametrize(
    "index",
    [
        pytest.param(_oci_index((ATTESTATION_DIGEST, "unknown", "unknown")), id="none"),
        pytest.param(
            _oci_index((AMD64_DIGEST, "linux", "amd64"), (ATTESTATION_DIGEST, "linux", "amd64")),
            id="two",
        ),
    ],
)
def test_an_index_without_exactly_one_amd64_manifest_is_refused(index):
    with pytest.raises(delta.ReleaseLayerError, match="linux/amd64"):
        delta.amd64_layers(index, lambda _digest: _image_manifest(BASE_LAYERS))


def test_a_document_that_is_neither_index_nor_manifest_is_refused():
    with pytest.raises(delta.ReleaseLayerError, match="neither"):
        delta.amd64_layers({"schemaVersion": 2}, lambda _digest: {})


def test_shared_layers_are_kept_and_only_new_bytes_count():
    new = _layers(*BASE_LAYERS, NEW_TOP_LAYER)
    previous = _layers(*BASE_LAYERS, OLD_TOP_LAYER)

    result = delta.layer_delta(new, previous)

    assert [marked.is_new for marked in result.layers] == [False, False, True]
    assert (result.new_count, result.new_bytes) == (1, NEW_TOP_LAYER[1])
    assert result.total_bytes == sum(size for _, size in [*BASE_LAYERS, NEW_TOP_LAYER])


def test_an_identical_pair_pulls_nothing():
    layers = _layers(*BASE_LAYERS)

    result = delta.layer_delta(layers, layers)

    assert (result.new_count, result.new_bytes) == (0, 0)


def test_without_a_previous_image_every_layer_is_new():
    result = delta.layer_delta(_layers(*BASE_LAYERS), ())

    assert result.new_count == len(BASE_LAYERS)
    assert result.new_bytes == result.total_bytes


def test_the_summary_line_carries_the_counts_and_megabytes_of_the_delta():
    result = delta.layer_delta(_layers(*BASE_LAYERS, NEW_TOP_LAYER), _layers(*BASE_LAYERS))

    text = delta.render(IMAGE, "2026.11.11.2", "2026.11.11.1", result)

    assert "pulls 1 of 3 layers, 60.0 MB of 4090.0 MB" in text.splitlines()[-1]
    assert text.splitlines()[0] == f"{IMAGE} 2026.11.11.2 against 2026.11.11.1"
    assert f"{NEW_TOP_LAYER[0][:19]}  60.0 MB  new" in text
    assert f"{BASE_LAYERS[0][0][:19]}  30.0 MB  kept" in text


# --- the registry boundary and the command, against a stand-in docker -------------------

NEW_VERSION = "2026.11.11.2"
PREVIOUS_VERSION = "2026.11.11.1"
TAG_REFS = f"refs/tags/v{PREVIOUS_VERSION}\nrefs/tags/v2026.11.10.4\n"
FAKE_DOCKER = """\
#!{python}
import json, sys
reference = sys.argv[-1]
registry = json.load(open({registry_file!r}))
if reference in registry:
    sys.stderr.write(registry[reference].get("stderr", ""))
    print(registry[reference]["stdout"], end="")
    sys.exit(registry[reference].get("exit", 0))
sys.stderr.write("ERROR: " + reference + ": not found\\n")
sys.exit(1)
"""


def _tag_reference(version: str) -> str:
    return f"ghcr.io/{REPOSITORY.lower()}/{IMAGE}:{version}"


def _registry_entry(document: dict) -> dict:
    return {"stdout": json.dumps(document)}


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """A stand-in `docker` on PATH serving the entries the test puts in the returned dict."""
    entries: dict[str, dict] = {}
    registry_file = tmp_path / "registry.json"
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    docker = binary_directory / "docker"
    docker.write_text(FAKE_DOCKER.format(python=sys.executable, registry_file=str(registry_file)))
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(binary_directory))

    class Registry(dict):
        def publish(self, version: str, layers: list[tuple[str, int]], digest: str) -> None:
            self[_tag_reference(version)] = _registry_entry(_oci_index((digest, "linux", "amd64")))
            self[f"{_tag_reference(version).rpartition(':')[0]}@{digest}"] = _registry_entry(
                _image_manifest(layers)
            )
            registry_file.write_text(json.dumps(self))

        def save(self) -> None:
            registry_file.write_text(json.dumps(self))

    registry_dict = Registry(entries)
    registry_file.write_text("{}")
    return registry_dict


def _run_release_layer_command(
    monkeypatch, capsys, refs: str = TAG_REFS, version: str = NEW_VERSION
):
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(refs))
    argv = ["--repository", REPOSITORY, "--image", IMAGE, "--version", version]
    exit_code = delta.main(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_the_command_prints_the_table_against_the_previous_release(registry, monkeypatch, capsys):
    registry.publish(NEW_VERSION, [*BASE_LAYERS, NEW_TOP_LAYER], "sha256:" + "3" * 64)
    registry.publish(PREVIOUS_VERSION, [*BASE_LAYERS, OLD_TOP_LAYER], "sha256:" + "4" * 64)

    exit_code, out, err = _run_release_layer_command(monkeypatch, capsys)

    assert (exit_code, err) == (0, "")
    assert out.splitlines()[0] == f"{IMAGE} {NEW_VERSION} against {PREVIOUS_VERSION}"
    assert f"a node holding {PREVIOUS_VERSION} pulls 1 of 3 layers, 60.0 MB of 4090.0 MB" in out


def test_the_command_without_an_earlier_tag_marks_every_layer_new(registry, monkeypatch, capsys):
    registry.publish(NEW_VERSION, BASE_LAYERS, "sha256:" + "3" * 64)

    exit_code, out, _err = _run_release_layer_command(
        monkeypatch, capsys, refs="refs/tags/v2030.01.01.1\n"
    )

    assert exit_code == 0
    assert out.splitlines()[0] == f"{IMAGE} {NEW_VERSION} against no earlier release"
    assert out.count("  new") == len(BASE_LAYERS)
    assert "kept" not in out


@pytest.mark.parametrize("missing_marker", ["not found", "manifest unknown"])
def test_the_command_says_so_when_the_previous_release_has_no_such_image(
    registry, monkeypatch, capsys, missing_marker
):
    registry.publish(NEW_VERSION, BASE_LAYERS, "sha256:" + "3" * 64)
    registry[_tag_reference(PREVIOUS_VERSION)] = {
        "stdout": "",
        "exit": 1,
        "stderr": missing_marker,
    }
    registry.save()

    exit_code, out, _err = _run_release_layer_command(monkeypatch, capsys)

    assert exit_code == 0
    assert (
        f"the previous release {PREVIOUS_VERSION} has no {IMAGE} image: every layer is new" in out
    )
    assert out.count("  new") == len(BASE_LAYERS)


def test_the_command_fails_naming_the_image_when_the_new_tag_cannot_be_read(
    registry, monkeypatch, capsys
):
    exit_code, out, err = _run_release_layer_command(monkeypatch, capsys)

    assert (exit_code, out) == (1, "")
    assert IMAGE in err
    assert err.count("\n") == 1


def test_the_command_relays_a_registry_failure_other_than_not_found(registry, monkeypatch, capsys):
    registry[_tag_reference(NEW_VERSION)] = {
        "stdout": "",
        "exit": 1,
        "stderr": "denied: permission_denied",
    }
    registry.save()

    exit_code, out, err = _run_release_layer_command(monkeypatch, capsys)

    assert (exit_code, out) == (1, "")
    assert IMAGE in err
    assert "denied: permission_denied" in err


def test_the_command_fails_on_malformed_json(registry, monkeypatch, capsys):
    registry[_tag_reference(NEW_VERSION)] = {"stdout": "<html>"}
    registry.save()

    exit_code, _out, err = _run_release_layer_command(monkeypatch, capsys)

    assert exit_code == 1
    assert f"{IMAGE}:" in err


def test_a_malformed_version_is_a_usage_error(monkeypatch, capsys):
    with pytest.raises(SystemExit) as raised:
        _run_release_layer_command(monkeypatch, capsys, version="v1")

    assert raised.value.code == 2
