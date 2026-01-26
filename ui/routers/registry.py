"""
Router registry for admin UI.
"""

from __future__ import annotations

from typing import Callable, Iterable

from aiogram import Dispatcher

from ui.handlers.gain_alerts import GainAlertsHandler
from ui.handlers.userbots import UserbotsHandler
from ui.handlers.settings import SettingsHandler
from ui.handlers.command_forwarding import CommandForwardingHandler


def get_router_factories(
    gain_alerts_handler: GainAlertsHandler,
    userbots_handler: UserbotsHandler,
    settings_handler: SettingsHandler,
    cmd_fwd_handler: CommandForwardingHandler,
) -> Iterable[Callable[[Dispatcher], None]]:
    from . import gain_alerts, userbots, settings, command_forwarding  # noqa: WPS433

    return (
        lambda dp: gain_alerts.register(dp, gain_alerts_handler),
        lambda dp: userbots.register(dp, userbots_handler),
        lambda dp: settings.register(dp, settings_handler),
        lambda dp: command_forwarding.register(dp, cmd_fwd_handler),
    )
