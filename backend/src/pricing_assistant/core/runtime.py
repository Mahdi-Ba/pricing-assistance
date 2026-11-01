"""Per-process resources for workers.

Async database engines are bound to the event loop that first uses them. Dramatiq runs async
actors on its own event-loop thread, so worker resources are created lazily on first use there.
"""

from pydantic import SecretStr

from pricing_assistant.core.db import Database, create_engine


class LazyDatabase:
    def __init__(self, url: SecretStr, *, pool_size: int) -> None:
        self._url = url
        self._pool_size = pool_size
        self._db: Database | None = None

    def __call__(self) -> Database:
        if self._db is None:
            self._db = Database(create_engine(self._url, pool_size=self._pool_size))
        return self._db

    async def dispose(self) -> None:
        if self._db is not None:
            await self._db.dispose()
            self._db = None
