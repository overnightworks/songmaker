"""The owner lease's old key, kept beside tandem's lease for one release.

Web, music worker and scoring worker are three deployments that do not restart together, so a
process of the previous release can still renew ``<prefix>:owner:<id>`` and read only that key.
Every process of this release writes the old key while it keeps its lease and reads an owner as
alive when either the lease or the old key is live, so no process of either release reads the other
as gone. The module is staged for one release: deleting it and building plain ``Leases`` in
``worker_liveness.owner_leases`` ends the stage.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from contextlib import suppress
from datetime import timedelta

from redis.exceptions import RedisError
from tandem import Client, Leases, LeaseState, Liveness, Renewal
from tandem.errors import store_error

log = logging.getLogger(__name__)


def old_owner_key(key_prefix: str, owner_id: str) -> str:
    """The key the previous release renews for the process ``owner_id``."""
    return f"{key_prefix}:owner:{owner_id}"


class OwnerLeasesWithOldKey(Leases):
    """``Leases`` that also write, end and read the old key of each owner.

    The old key rides the renewals and the end of ``Leases.kept``, so its guarantee that an
    in-flight renewal completes before the end, even when the exit is cancelled, holds for it too.
    """

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

    async def state(self, holders: Collection[str]) -> dict[str, LeaseState]:
        """The lease's state, with an owner whose old key is live read as ALIVE."""
        states = await super().state(holders)
        unconfirmed = [
            holder for holder, state in states.items() if state.liveness is not Liveness.ALIVE
        ]
        if not unconfirmed:
            return states
        try:
            keys = [old_owner_key(self._old_key_prefix, holder) for holder in unconfirmed]
            renewed = await self._old_key_client.mget(keys)
        except RedisError as error:
            raise store_error("reading the old owner keys", error) from error
        return states | {
            holder: LeaseState(Liveness.ALIVE, generation=None, remaining=None)
            for holder, value in zip(unconfirmed, renewed, strict=True)
            if value is not None
        }

    async def renew(self, holder: str) -> Renewal:
        """Renew the lease, then its old key: a failed old-key write is only logged."""
        renewal = await super().renew(holder)
        try:
            await self._old_key_client.set(
                old_owner_key(self._old_key_prefix, holder),
                "1",
                ex=int(self._old_key_lasts.total_seconds()),
            )
        except RedisError:
            log.warning("Could not renew the old owner key", exc_info=True)
        return renewal

    async def end(self, holder: str, generation: str) -> bool:
        """End the lease and drop its old key."""
        try:
            return await super().end(holder, generation)
        finally:
            with suppress(RedisError):
                await self._old_key_client.delete(old_owner_key(self._old_key_prefix, holder))
