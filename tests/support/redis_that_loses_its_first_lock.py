"""A Redis client whose server forgets everything right after the first script reply.

The first script a lock runs is its acquisition, so the lock runs out before its holder's entry
polls it again; the client is the injected port, so no production symbol is replaced.
"""

from collections.abc import Callable

from redis.asyncio import Redis

SCRIPT_COMMANDS = frozenset({"EVAL", "EVALSHA"})


class RedisThatLosesItsFirstLock(Redis):
    """``when_lost`` runs once, after the reply of the first script the client sends."""

    when_lost: Callable[[], None]
    lost: bool = False

    async def execute_command(self, *args, **options):
        reply = await super().execute_command(*args, **options)
        if not self.lost and str(args[0]).upper() in SCRIPT_COMMANDS:
            self.lost = True
            self.when_lost()
        return reply
