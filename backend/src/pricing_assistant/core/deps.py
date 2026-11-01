"""FastAPI dependencies for process-wide resources stored on ``app.state``."""

from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis

from pricing_assistant.core.db import Database
from pricing_assistant.core.settings import Settings


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


DatabaseDep = Annotated[Database, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
