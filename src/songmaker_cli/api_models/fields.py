"""Field types shared by the API response models."""

from __future__ import annotations

ComputedTimestamp = str | None
"""An ISO-8601 timestamp the response computes rather than reads.

``None`` is a real answer here, not a missing value: a picked generation
never expires, and a co-writer memory scope that was never written has no
update time. Nullability on a timestamp that *does* come from a NOT NULL
column is a lie the no-silent-fallbacks check rejects — this named type
marks the cases where the null is part of the contract.
"""
