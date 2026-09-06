"""The image contract a host lends the provider layer.

This package produces an image by driving someone else's CLI; what counts as
an acceptable one is the host's decision. A host states it once as an
:class:`ImagePolicy` and hands it to the image route, which refuses anything
outside it instead of guessing a size, a format, or a ceiling of its own.

Self-contained by design: pydantic only, no application import, so the
package can be released on its own (issue #825).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ImagePolicy(BaseModel):
    """What a host accepts from one generated image, and what it wants back.

    ``output_format`` is the encoder the produced image is written with, and
    ``output_signature`` the leading bytes that encoder must have written —
    the host states both, so a route can prove it returned the format it was
    asked for rather than trusting the encoder's word.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    maximum_source_bytes: int = Field(gt=0)
    maximum_pixels: int = Field(gt=0)
    output_edge_pixels: int = Field(gt=0)
    output_format: str = Field(min_length=1)
    output_signature: bytes = Field(min_length=1)
