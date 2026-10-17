from .base import PluginContext, PluginSpec, Services
from . import (
    channel_admin,
    channel_stats,
    crypto_alerts,
    currency,
    drive,
    images,
    links,
    metadata,
    notes,
    polls,
    qr,
    reminders,
    scheduler,
    text_tools,
    tiktok,
    translator,
)

_MODULES = (
    tiktok,
    drive,
    channel_admin,
    channel_stats,
    metadata,
    qr,
    notes,
    reminders,
    polls,
    scheduler,
    translator,
    images,
    text_tools,
    currency,
    links,
    crypto_alerts,
)

PLUGINS: dict[str, PluginSpec] = {m.SPEC.name: m.SPEC for m in _MODULES}

__all__ = ["PLUGINS", "PluginContext", "PluginSpec", "Services"]
