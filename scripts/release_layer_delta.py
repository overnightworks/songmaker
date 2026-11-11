"""Release step: print which layers of a release image are new and how many bytes a node pulls.

A node that holds the previous release's image pulls only the layers its copy
lacks. This prints the new image's layers in manifest order, marks each one
``new`` or ``kept`` against the highest earlier release tag, and sums the bytes
a node holding that release pulls. The tag list comes on stdin, one git ref per
line; the layers come from the registry through ``docker buildx imagetools``.

    gh api --paginate "repos/$REPOSITORY/git/matching-refs/tags/v" --jq '.[].ref' \\
        | python3 scripts/release_layer_delta.py --repository "$REPOSITORY" \\
            --image web --version 2026.11.11.2

Exit 0 when the table printed, 1 when the registry or its answer fails, 2 on usage.
"""
# ruff: noqa: T201 - this script prints the layer table of a release image

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

REGISTRY = "ghcr.io"
VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)\.(\d+)")
TAG_REFERENCE_PATTERN = re.compile(r"refs/tags/v(\d+\.\d+\.\d+\.\d+)")
MISSING_IMAGE_MARKERS = ("not found", "manifest unknown")
AMD64_PLATFORM = ("linux", "amd64")
DIGEST_PREFIX_LENGTH = len("sha256:") + 12
BYTES_PER_MEGABYTE = 1_000_000

ManifestDocument = Mapping[str, Any]
ManifestReader = Callable[[str], ManifestDocument]


class ReleaseLayerError(Exception):
    """The registry or its answer does not let the layers be read."""


class ImageNotFoundError(ReleaseLayerError):
    """The registry has no manifest under the reference."""


@dataclass(frozen=True)
class Layer:
    digest: str
    size: int


@dataclass(frozen=True)
class MarkedLayer:
    layer: Layer
    is_new: bool


@dataclass(frozen=True)
class LayerDelta:
    layers: tuple[MarkedLayer, ...]

    @property
    def new_count(self) -> int:
        return sum(marked.is_new for marked in self.layers)

    @property
    def new_bytes(self) -> int:
        return sum(marked.layer.size for marked in self.layers if marked.is_new)

    @property
    def total_bytes(self) -> int:
        return sum(marked.layer.size for marked in self.layers)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def previous_version(refs: Iterable[str], version: str) -> str | None:
    """The highest ``YYYY.MM.DD.N`` tag strictly below ``version``, or None."""
    tagged = (
        match.group(1) for ref in refs if (match := TAG_REFERENCE_PATTERN.fullmatch(ref.strip()))
    )
    earlier = [tag for tag in tagged if _version_key(tag) < _version_key(version)]
    return max(earlier, key=_version_key, default=None)


def _platform_of(entry: ManifestDocument) -> tuple[object, object]:
    platform = entry.get("platform", {})
    return platform.get("os"), platform.get("architecture")


def amd64_layers(document: ManifestDocument, read_manifest: ManifestReader) -> tuple[Layer, ...]:
    """The ordered layers of the one linux/amd64 image an index or manifest list names."""
    if "manifests" in document:
        entries = [
            entry for entry in document["manifests"] if _platform_of(entry) == AMD64_PLATFORM
        ]
        if len(entries) != 1:
            raise ReleaseLayerError(
                f"the index holds {len(entries)} linux/amd64 manifests, not one"
            )
        document = read_manifest(entries[0]["digest"])
    if "layers" not in document:
        raise ReleaseLayerError("the document is neither an index nor an image manifest")
    return tuple(Layer(digest=entry["digest"], size=entry["size"]) for entry in document["layers"])


def layer_delta(new: Sequence[Layer], previous: Sequence[Layer]) -> LayerDelta:
    held = {layer.digest for layer in previous}
    return LayerDelta(tuple(MarkedLayer(layer, layer.digest not in held) for layer in new))


def _megabytes(size: int) -> str:
    return f"{size / BYTES_PER_MEGABYTE:.1f} MB"


def render(
    image: str,
    version: str,
    previous: str | None,
    delta: LayerDelta,
    previous_image_missing: bool = False,
) -> str:
    held = previous or "no earlier release"
    lines = [f"{image} {version} against {held}"]
    if previous_image_missing:
        lines.append(f"the previous release {previous} has no {image} image: every layer is new")
    lines.extend(
        f"{marked.layer.digest[:DIGEST_PREFIX_LENGTH]}  {_megabytes(marked.layer.size)}  "
        + ("new" if marked.is_new else "kept")
        for marked in delta.layers
    )
    lines.append(
        f"a node holding {held} pulls {delta.new_count} of {len(delta.layers)} layers, "
        f"{_megabytes(delta.new_bytes)} of {_megabytes(delta.total_bytes)}"
    )
    return "\n".join(lines)


def image_reference(repository: str, image: str) -> str:
    return f"{REGISTRY}/{repository.lower()}/{image}"


def read_registry_manifest(reference: str) -> ManifestDocument:
    """The JSON document the registry stores under ``reference`` (a tag or a digest)."""
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", "--raw", reference],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        error_class = (
            ImageNotFoundError
            if any(marker in result.stderr.lower() for marker in MISSING_IMAGE_MARKERS)
            else ReleaseLayerError
        )
        raise error_class(result.stderr.strip() or f"docker exited {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ReleaseLayerError(f"{reference} answered malformed JSON: {error}") from error


def _layers_of(base: str, tag: str, read_reference: ManifestReader) -> tuple[Layer, ...]:
    def read_digest(digest: str) -> ManifestDocument:
        return read_reference(f"{base}@{digest}")

    return amd64_layers(read_reference(f"{base}:{tag}"), read_digest)


def report(
    refs: Iterable[str],
    repository: str,
    image: str,
    version: str,
    read_reference: ManifestReader,
) -> str:
    """The printed text for one image, reading the registry only through ``read_reference``."""
    base = image_reference(repository, image)
    previous = previous_version(refs, version)
    new_layers = _layers_of(base, version, read_reference)
    previous_layers: tuple[Layer, ...] = ()
    previous_image_missing = False
    if previous is not None:
        try:
            previous_layers = _layers_of(base, previous, read_reference)
        except ImageNotFoundError:
            previous_image_missing = True
    return render(
        image, version, previous, layer_delta(new_layers, previous_layers), previous_image_missing
    )


def _version(text: str) -> str:
    if not VERSION_PATTERN.fullmatch(text):
        raise argparse.ArgumentTypeError(f"{text!r} is not of the form YYYY.MM.DD.N")
    return text


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--version", required=True, type=_version)
    arguments = parser.parse_args(argv)
    try:
        print(
            report(
                sys.stdin.read().splitlines(),
                arguments.repository,
                arguments.image,
                arguments.version,
                read_registry_manifest,
            )
        )
    except ReleaseLayerError as error:
        print(f"{arguments.image}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
