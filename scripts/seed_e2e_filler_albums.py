"""Bulk-seed the e2e rail test's filler albums directly against the database.

``frontend/e2e/seed.ts`` needs enough closed rail rows to overflow the rail's
own scroll region for the Settings/user-row pin promise (issue #326). That
used to be 30 individual ``POST /api/albums`` calls from the Playwright
process. Issue #344's CI root-cause analysis found this was most of what
pushed a run over the IP rate limit: the server's rate limiter counts every
request it receives regardless of which Playwright context sent it, and
these 30 requests exercise no API semantics worth spending that budget on --
they only need the rows to exist. This does the same inserts in one process
instead, through the exact same slug-uniqueness path the API itself uses
(``unique_album_id``), so a filler album can never collide with a real one
or with a previous local run's leftovers.

Run inside the web container, where ``DATABASE_URL`` is mounted. Use the
venv's Python directly -- bare ``python`` on the container's ``PATH`` is the
package-less system interpreter, not the app's:

    docker compose exec -T songmaker-web /app/.venv/bin/python \\
        scripts/seed_e2e_filler_albums.py \\
        --count 30 --title-prefix "E2E Rail Filler mtizek8x" \\
        --owner-username e2e-ci-admin

This connects to the database only -- it never runs schema migrations, even
implicitly, matching every other one-off script here (see ``connect_db()``
in ``db/engine.py``).
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import unique_album_id
from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.db.queries import create_album, get_user_by_username


def seed_filler_albums(
    session: Session, *, count: int, title_prefix: str, owner_id: str,
) -> int:
    """Create ``count`` songless albums titled ``{title_prefix}-{index}``."""
    for index in range(count):
        title = f"{title_prefix}-{index}"
        album_id = unique_album_id(session, title)
        create_album(session, album_id, title, created_by=owner_id)
    session.commit()
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--title-prefix", required=True)
    parser.add_argument("--owner-username", required=True)
    args = parser.parse_args(argv)

    factory = connect_db(resolve_database_url())
    with factory() as session:
        owner = get_user_by_username(session, args.owner_username)
        if owner is None:
            print(f"No user named {args.owner_username!r}", file=sys.stderr)
            return 1
        created = seed_filler_albums(
            session, count=args.count, title_prefix=args.title_prefix, owner_id=owner.id,
        )

    print(f"Seeded {created} filler albums owned by {args.owner_username!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
