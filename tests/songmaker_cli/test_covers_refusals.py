"""A refused cover is answered with the status, sentence and catalog key of its reason."""

from __future__ import annotations

import pytest

from songmaker_cli.api_helpers import raise_cover_refusal
from songmaker_cli.covers import CoverRejectedError, CoverRejection
from songmaker_cli.refusals import Refusal


@pytest.mark.parametrize(
    ("reason", "status", "key", "sentence"),
    [
        (CoverRejection.TOO_LARGE, 413, "coverRefusal.tooLarge", "Cover file is too large"),
        (
            CoverRejection.UNREADABLE, 422, "coverRefusal.unreadable",
            "Cover image could not be read",
        ),
        (
            CoverRejection.UNSUPPORTED_TYPE, 422, "coverRefusal.unsupportedType",
            "Cover must be a JPEG or PNG image",
        ),
        (
            CoverRejection.TOO_MANY_PIXELS, 422, "coverRefusal.tooManyPixels",
            "Cover image is too large",
        ),
        (
            CoverRejection.VARIANT_UNKNOWN, 422, "coverRefusal.variantUnknown",
            "Unknown cover variant",
        ),
        (
            CoverRejection.INVALID_ALBUM_ID, 422, "coverRefusal.invalidAlbumId",
            "Invalid album id for cover storage",
        ),
        (
            CoverRejection.INVALID_SONG_ID, 422, "coverRefusal.invalidSongId",
            "Invalid song id for cover storage",
        ),
        (
            CoverRejection.INVALID_PLAYLIST_ID, 422, "coverRefusal.invalidPlaylistId",
            "Invalid playlist id for cover storage",
        ),
    ],
)
def test_each_cover_rejection_is_refused_with_its_status_sentence_and_key(
    reason: CoverRejection, status: int, key: str, sentence: str,
) -> None:
    with pytest.raises(Refusal) as refused:
        raise_cover_refusal(CoverRejectedError(reason))

    assert (refused.value.status_code, refused.value.detail) == (status, sentence)
    assert (refused.value.key, refused.value.gaps) == (key, {})
