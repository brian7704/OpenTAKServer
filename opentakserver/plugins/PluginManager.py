from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Flask

from opentakserver.extensions import logger
from opentakserver.plugins.Plugin import Plugin
from poetry.utils._compat import metadata


if TYPE_CHECKING:
    from typing import Any


class PluginManager:
    """
    This class registers and activates plugins.
    """

    def __init__(self, group: str, app: Flask) -> None:
        self._group = group
        self._plugins: dict[str, Plugin] = {}
        self._app = app

    def load_plugins(self) -> None:
        plugin_entrypoints = self.get_plugin_entry_points()
        for ep in plugin_entrypoints:
            self._load_plugin_entry_point(ep)

    def get_plugin_entry_points(self) -> list[metadata.EntryPoint]:
        return list(metadata.entry_points(group=self._group))

    def activate(self, *args: Any, **kwargs: Any) -> None:
        logger.info(self._plugins)
        for distro, plugin in self._plugins.items():
            try:
                plugin.activate(*args, **kwargs)
                if plugin.blueprint:
                    self._app.register_blueprint(plugin.blueprint)
            except BaseException as e:
                print(f"Failed to load plugin: {e}")

    def stop_plugins(self):
        for distro, plugin in self._plugins.items():
            plugin.stop()

    def disable_plugin(self, plugin_distro: str):
        self._plugins[plugin_distro].stop()
        logger.info(f"{plugin_distro} disabled")

    def enable_plugin(self, plugin_distro: str):
        self._plugins[plugin_distro].activate(self._app)
        logger.info(f"{plugin_distro} enabled")

    def _add_plugin(self, plugin: Plugin) -> None:
        if not isinstance(plugin, Plugin):
            raise ValueError(
                "The OTS plugin must be an instance of Plugin"
            )

        plugin.load_metadata()
        self._plugins[plugin.distro] = plugin

    def _load_plugin_entry_point(self, ep: metadata.EntryPoint) -> None:
        logger.debug("Loading the %s plugin", ep.name)

        plugin = ep.load()

        if not issubclass(plugin, Plugin):
            raise ValueError(
                "The OTS plugin must be an instance of Plugin"
            )

        self._add_plugin(plugin())
