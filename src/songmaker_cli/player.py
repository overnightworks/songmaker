"""Generate a manifest.json and static HTML player for all albums.

Thin orchestrator — delegates manifest building to manifest.py,
filesystem scanning to scanner.py, and just handles HTML rendering
and file output here.
"""

from __future__ import annotations

import json
from pathlib import Path
from string import Template

from songmaker_cli.constants import DEFAULT_ARTIST, default_year
from songmaker_cli.manifest import build_manifest

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_player(output_dir: Path, project_root: Path | None = None) -> Path:
    """Scan all albums, write manifest.json, and ensure player.html exists.

    Args:
        output_dir: Where to write files (usually _output/).
        project_root: Project root for finding album.yaml and lyrics.

    Returns:
        Path to the player.html.
    """
    if project_root is None:
        project_root = output_dir.parent

    manifest = build_manifest(output_dir, project_root)
    manifest_dict = manifest.to_dict()

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    player_path = output_dir / "player.html"
    manifest_json = json.dumps(manifest_dict, ensure_ascii=False)
    html = render_static_html(manifest_json, DEFAULT_ARTIST, default_year())
    player_path.write_text(html, encoding="utf-8")

    return player_path


def _escape_json_for_html(json_str: str) -> str:
    """Escape JSON for safe embedding inside an HTML <script> tag."""
    return json_str.replace("</", r"<\/").replace("<!--", r"<\!--")


def render_static_html(
    manifest_json: str = "null",
    artist: str = DEFAULT_ARTIST,
    year: str = "",
) -> str:
    """Render the HTML player from template with variable substitution."""
    if not year:
        year = default_year()
    template_path = _TEMPLATE_DIR / "player.html"
    template = Template(template_path.read_text(encoding="utf-8"))
    return template.substitute(
        ARTIST=artist,
        YEAR=year,
        MANIFEST_JSON=_escape_json_for_html(manifest_json),
    )
