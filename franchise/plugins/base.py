from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from aiogram import Bot, Router

from ..config import Settings
from ..db import Database
from ..drive import DriveClient


@dataclass(frozen=True)
class Services:
    settings: Settings
    db: Database
    drive: DriveClient
    http: httpx.AsyncClient


@dataclass(frozen=True)
class PluginContext:
    """Контекст одного экземпляра бота: владелец и изолированное хранилище."""

    services: Services
    owner_id: int
    plugin: str

    @property
    def scope(self) -> str:
        return f"{self.plugin}:{self.owner_id}"

    def get(self, key: str, default: Any = None) -> Any:
        return self.services.db.kv_get(self.scope, key, default)

    def set(self, key: str, value: Any) -> None:
        self.services.db.kv_set(self.scope, key, value)


Builder = Callable[[PluginContext], Router]
Background = Callable[[Bot, PluginContext], Awaitable[None]]


@dataclass(frozen=True)
class PluginSpec:
    name: str
    title: str
    icon: str
    description: str
    build: Builder
    commands: tuple[tuple[str, str], ...] = ()
    background: Background | None = None
    owner_only: bool = False
