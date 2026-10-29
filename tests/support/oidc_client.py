"""The OIDC client secret every test session runs under."""

from __future__ import annotations

import tempfile

TEST_CLIENT_SECRET = "test-client-secret"


def write_test_client_secret() -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".secret", delete=False) as secret_file:
        secret_file.write(TEST_CLIENT_SECRET)
    return secret_file.name
