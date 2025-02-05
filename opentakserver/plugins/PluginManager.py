from __future__ import annotations

import logging

from typing import TYPE_CHECKING

from opentakserver.plugins.Plugin import Plugin
from poetry.utils._compat import metadata


if TYPE_CHECKING:
    from typing import Any


logger = logging.getLogger(__name__)


class PluginManager:
    """
    This class registers and activates plugins.
    """

    def __init__(self, group: str) -> None:
        self._group = group
        self._plugins: list[Plugin] = []

    def load_plugins(self) -> None:
        plugin_entrypoints = self.get_plugin_entry_points()

        for ep in plugin_entrypoints:
            self._load_plugin_entry_point(ep)

    def get_plugin_entry_points(self) -> list[metadata.EntryPoint]:
        return list(metadata.entry_points(group=self._group))

    def activate(self, *args: Any, **kwargs: Any) -> None:
        for plugin in self._plugins:
            plugin.activate(*args, **kwargs)

    def _add_plugin(self, plugin: Plugin) -> None:
        if not isinstance(plugin, Plugin):
            raise ValueError(
                "The OTS plugin must be an instance of Plugin"
            )

        self._plugins.append(plugin)

    def _load_plugin_entry_point(self, ep: metadata.EntryPoint) -> None:
        logger.debug("Loading the %s plugin", ep.name)

        plugin = ep.load()

        if not issubclass(plugin, Plugin):
            raise ValueError(
                "The OTS plugin must be an instance of Plugin"
            )

        self._add_plugin(plugin())
