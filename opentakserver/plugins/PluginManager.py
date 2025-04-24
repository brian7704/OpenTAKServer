from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

import sqlalchemy.exc
from flask import Flask
from sqlalchemy import update

from opentakserver.extensions import logger, db
from opentakserver.models.Plugins import Plugins
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
                try:
                    with self._app.app_context():
                        plugin_metadata = plugin.load_metadata()
                        logger.warning(plugin_metadata)

                        # Add the plugin to the DB or update its version number
                        plugin_row = db.session.execute(db.session.query(Plugins).filter_by(name=plugin.name)).first()
                        if plugin_row:
                            plugin_row = plugin_row[0]
                            plugin_row.version = plugin_metadata.get("version")
                        else:
                            plugin_row = Plugins()
                            plugin_row.name = plugin.name
                            plugin_row.author = plugin_metadata.get("author")
                            plugin_row.version = plugin_metadata.get("version")
                            plugin_row.enabled = True

                        db.session.add(plugin_row)
                        db.session.commit()
                except sqlalchemy.exc.IntegrityError as e:
                    logger.error(f"Failed to insert {plugin.name}: {e}")

                plugin.activate(*args, **kwargs, enabled=self.check_if_plugin_enabled(plugin.name))
                if plugin.blueprint:
                    self._app.register_blueprint(plugin.blueprint)

            except BaseException as e:
                logger.error(f"Failed to load plugin: {e}")
                logger.error(traceback.format_exc())

    def stop_plugins(self):
        logger.warning(self._plugins)
        for distro, plugin in self._plugins.items():
            plugin.stop()

    def disable_plugin(self, plugin_distro: str):
        plugin = self._plugins[plugin_distro]
        plugin.stop()

        db.session.execute(update(Plugins).where(Plugins.name == plugin.name).values(enabled=False))
        db.session.commit()

        logger.info(f"{plugin_distro} disabled")

    def enable_plugin(self, plugin_distro: str):
        plugin = self._plugins[plugin_distro]
        plugin.activate(self._app, True)

        db.session.execute(update(Plugins).where(Plugins.name == plugin.name).values(enabled=True))
        db.session.commit()

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

        try:
            self._add_plugin(plugin())
        except BaseException as e:
            logger.error(f"Failed to load plugin: {e}")
            logger.error(traceback.format_exc())

    def check_if_plugin_enabled(self, plugin_name: str) -> bool:
        with self._app.app_context():
            plugin = db.session.execute(db.session.query(Plugins).filter_by(name=plugin_name)).first()
            if plugin:
                logger.warning(plugin)
                return plugin[0].enabled
            else:
                # First time this plugin has been loaded, enable it by default
                return True
