from __future__ import annotations

import sys
from pathlib import Path

from requirement_contract import RequirementContractError, read_requirement_shelf
from requirement_witness import HttpsGitHubClient, LiveWitnessError, verify_live_witnesses


def main() -> int:
    try:
        project_root = Path.cwd()
        shelf = read_requirement_shelf(project_root)
        if not shelf.revisions:
            count = 0
        else:
            count = verify_live_witnesses(
                project_root,
                HttpsGitHubClient.from_environment(),
                shelf=shelf,
            )
    except (RequirementContractError, LiveWitnessError) as error:
        print(f"Live witness gate refused: {error}", file=sys.stderr)
        return 1
    print(
        f"Live witness check: {count} approval witness(es) matched GitHub "
        "(point-in-time)"
    )
    if count == 0:
        print("No network request was made because the registry is empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
