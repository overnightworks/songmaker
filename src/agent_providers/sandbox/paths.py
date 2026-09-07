"""The private directory names a host's mount policy has to permit.

Every confined Codex run — the album-cover image turn, the co-writer tool
turn, and the proof that the deployment's sandbox still holds — works inside
Bubblewrap with exactly one writable place: a ``codex-home`` below a directory
named by one of these prefixes. The host permits those mounts and nothing
else, so each name is a contract between this package and a policy file the
host loads into its kernel: songmaker's AppArmor profile
(``scripts/apparmor/songmaker-web``) spells all three, and
``tests/test_prove_codex_image_sandbox.py`` holds the profile to this module.
Stating a name once here is what makes a rename a red test instead of a
silently refused mount at the next turn (issue #876).

The names carry songmaker's product name because songmaker is the host that
owns that profile and the ``/tmp`` namespace the directories live in. A
project embedding this package brings its own profile and derives it from
these constants; when a second host exists, naming that namespace becomes its
own injected deployment fact, the way ``cli_working_directory_root`` and
``cli_prompt_file_prefix`` already are.
"""

from __future__ import annotations

from typing import Final

CODEX_IMAGE_TURN_DIRECTORY_PREFIX: Final = "songmaker-cover-codex-"
CODEX_TOOL_TURN_DIRECTORY_PREFIX: Final = "songmaker-codex-tool-"
CODEX_SANDBOX_PROOF_DIRECTORY: Final = "songmaker-codex-sandbox-probe"
CODEX_HOME_DIRECTORY_NAME: Final = "codex-home"
