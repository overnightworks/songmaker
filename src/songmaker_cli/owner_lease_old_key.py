"""The owner lease's old key, kept beside tandem's lease for one release.

Web, music worker and scoring worker are three deployments that do not restart together, so a
process of the previous release can still renew ``<prefix>:owner:<id>`` and read only that key.
Every process of this release writes the old key while it keeps its lease and reads an owner as
alive when either the lease or the old key is live, so no process of either release reads the other
as gone. The module is staged for one release: deleting it and building plain ``Leases`` in
``worker_liveness.owner_leases`` ends the stage.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager, suppress
from datetime import timedelta

from redis.exceptions import RedisError
from tandem import Client, Hold, Leases, Liveness, StoreError

log = logging.getLogger(__name__)


def old_owner_key(key_prefix: str, owner_id: str) -> str:
    """The key the previous release renews for the process ``owner_id``."""
    return f"{key_prefix}:owner:{owner_id}"


class OwnerLeasesWithOldKey(Leases):
    """``Leases`` that also write and read the old key of each owner."""

    def __init__(
        self,
        redis: Client,
        *,
        key_prefix: str,
        family: str,
        lasts: timedelta,
        claim_for: timedelta,
    ) -> None:
        super().__init__(
            redis, key_prefix=key_prefix, family=family, lasts=lasts, claim_for=claim_for,
        )
        self._old_key_client = redis
        self._old_key_prefix = key_prefix
        self._old_key_lasts = lasts

    async def liveness(self, holders: Collection[str]) -> dict[str, Liveness]:
        """The lease's reading, with an owner whose old key is live read as ALIVE."""
        readings = await super().liveness(holders)
        unconfirmed = [
            holder for holder, reading in readings.items() if reading is not Liveness.ALIVE
        ]
        if not unconfirmed:
            return readings
        try:
            keys = [old_owner_key(self._old_key_prefix, holder) for holder in unconfirmed]
            renewed = await self._old_key_client.mget(keys)
        except RedisError as error:
            raise StoreError("reading the old owner keys failed", outage=True) from error
        return readings | {
            holder: Liveness.ALIVE
            for holder, value in zip(unconfirmed, renewed, strict=True)
            if value is not None
        }

    @asynccontextmanager
    async def kept(self, holder: str, *, every: timedelta) -> AsyncIterator[Hold]:
        """Keep the lease for the block; its old key is renewed beside it and dropped at exit."""
        async with super().kept(holder, every=every) as hold:
            key = old_owner_key(self._old_key_prefix, holder)
            await self._renew_old_key(key)
            renewing = asyncio.create_task(self._renew_old_key_every(key, every))
            try:
                yield hold
            finally:
                renewing.cancel()
                await asyncio.gather(renewing, return_exceptions=True)
                await self._drop_old_key(key)

    async def _renew_old_key(self, key: str) -> None:
        """Renew the old key; a failure is logged, for the lease is what this process proves."""
        try:
            await self._old_key_client.set(key, "1", ex=int(self._old_key_lasts.total_seconds()))
        except RedisError:
            log.warning("Could not renew the old owner key", exc_info=True)

    async def _renew_old_key_every(self, key: str, every: timedelta) -> None:
        while True:
            await asyncio.sleep(every.total_seconds())
            await self._renew_old_key(key)

    async def _drop_old_key(self, key: str) -> None:
        with suppress(RedisError):
            await self._old_key_client.delete(key)
