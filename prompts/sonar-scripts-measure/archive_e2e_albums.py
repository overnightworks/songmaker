# ruff: noqa: E402
"""Archive albums left by earlier Playwright runs on the isolated stack.

The browser suite deliberately keeps its evidence instead of deleting it, but
the rail lists every live album. Without this preparation, each local rerun
adds another page of filler rows and another set of cover requests to flows
whose request budgets are measured against a clean library.

Run inside the web container, where ``DATABASE_URL`` is mounted:

    docker compose exec -T songmaker-web /app/.venv/bin/python \
        scripts/archive_e2e_albums.py \
        --title-prefix "E2E " --owner-username e2e-ci-admin

Only live albums owned by the named test user and carrying the explicit test
prefix are archived. Their songs, takes, covers, and share links remain intact.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from _repo_path import prepend_own_checkout_src
from sqlalchemy import select
from sqlalchemy.orm import Session

prepend_own_checkout_src(__file__)

from songmaker_cli.db.engine import connect_db, resolve_database_url
from songmaker_cli.db.models import Album
from songmaker_cli.db.queries import get_user_by_username


def archive_e2e_albums(
    session: Session, *, owner_id: str, title_prefix: str,
) -> int:
    """Archive this test owner's live albums whose titles carry the prefix."""
    albums = session.scalars(
        select(Album).where(
            Album.created_by == owner_id,
            Album.is_archived.is_(False),
            Album.title.startswith(title_prefix),
        ),
    ).all()
    archived_at = datetime.now(timezone.utc)
    for album in albums:
        album.is_archived = True
        album.archived_at = archived_at
    session.commit()
    return len(albums)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title-prefix", required=True)
    parser.add_argument("--owner-username", required=True)
    args = parser.parse_args(argv)

    factory = connect_db(resolve_database_url())
    with factory() as session:
        owner = get_user_by_username(session, args.owner_username)
        if owner is None:
            print(f"No user named {args.owner_username!r}", file=sys.stderr)
            return 1
        archived = archive_e2e_albums(
            session, owner_id=owner.id, title_prefix=args.title_prefix,
        )

    print(f"Archived {archived} prior E2E albums owned by {args.owner_username!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
