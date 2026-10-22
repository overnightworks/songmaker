"""Songmaker command line — starts the web server."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

from cyclopts import App, Parameter

from songmaker_cli.settings import DEFAULT_SERVER_PORT

app = App(name="songmaker", help="AI-powered song generation platform.")


@app.command
def server(
    port: Annotated[int, Parameter(help="Server port")] = DEFAULT_SERVER_PORT,
    root: Annotated[Optional[str], Parameter(help="Project root")] = None,
    open_browser: Annotated[
        bool, Parameter(name="--open", help="Open browser on start"),
    ] = False,
) -> None:
    """Start the songmaker web server."""
    from songmaker_cli.server import run_server

    project_root = Path(root).resolve() if root else None
    run_server(project_root=project_root, port=port, open_browser=open_browser)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
