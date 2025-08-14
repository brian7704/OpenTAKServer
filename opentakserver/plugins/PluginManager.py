from __future__ import annotations

import os
import subprocess
import sys
import traceback
from typing import TYPE_CHECKING

import selectors
import sqlalchemy.exc
from flask import Flask, request, current_app as app
from sqlalchemy import update

from opentakserver.blueprints.ots_socketio import administrator_only
from opentakserver.extensions import logger, db, socketio
from opentakserver.models.Plugins import Plugins
from opentakserver.plugins.Plugin import Plugin
from poetry.utils._compat import metadata
from werkzeug.utils import secure_filename


if TYPE_CHECKING:
    from typing import Any


class PluginManager:
    """
    This class registers and activates plugins.
    """

    def __init__(self, group: str, app: Flask) -> None:
        self._group = group
        self.plugins: dict[str, Plugin] = {}
        self._app = app

    def load_plugins(self) -> None:
        plugin_entrypoints = self.get_plugin_entry_points()
        for ep in plugin_entrypoints:
            self._load_plugin_entry_point(ep)

    def get_plugin_entry_points(self) -> list[metadata.EntryPoint]:
        return list(metadata.entry_points(group=self._group))

    def activate(self, *args: Any, **kwargs: Any) -> None:
        for name, plugin in self.plugins.items():
            try:
                try:
                    with self._app.app_context():
                        plugin_metadata = plugin.load_metadata()

                        # Add the plugin to the DB or update its version number
                        plugin_row = db.session.execute(db.session.query(Plugins).filter_by(name=plugin.name.lower())).first()
                        if plugin_row:
                            plugin_row = plugin_row[0]
                            plugin_row.version = plugin_metadata.get("version")
                        else:
                            plugin_row = Plugins()
                            plugin_row.name = plugin.name.lower()
                            plugin_row.distro = plugin_metadata.get("distro")
                            plugin_row.author = plugin_metadata.get("author")
                            plugin_row.version = plugin_metadata.get("version")
                            plugin_row.enabled = True

                        db.session.add(plugin_row)
                        db.session.commit()
                except sqlalchemy.exc.IntegrityError as e:
                    logger.debug(f"{plugin_row.name} is already in the DB")
                except BaseException as e:
                    logger.debug(f"{plugin.name} already in the database")

                plugin.activate(*args, **kwargs, enabled=self.check_if_plugin_enabled(plugin.name))
                if plugin.blueprint:
                    self._app.register_blueprint(plugin.blueprint)

            except BaseException as e:
                logger.error(f"Failed to load plugin: {e}")
                logger.error(traceback.format_exc())

    def stop_plugins(self):
        for name, plugin in self.plugins.items():
            plugin.stop()

    def disable_plugin(self, plugin_distro: str):
        plugin = self.plugins[plugin_distro]
        plugin.stop()

        db.session.execute(update(Plugins).where(Plugins.name == plugin.name.lower()).values(enabled=False))
        db.session.commit()

        logger.info(f"{plugin_distro} disabled")

    def enable_plugin(self, plugin_distro: str):
        plugin = self.plugins[plugin_distro]
        plugin.activate(self._app, True)

        db.session.execute(update(Plugins).where(Plugins.name == plugin.name.lower()).values(enabled=True))
        db.session.commit()

        logger.info(f"{plugin_distro} enabled")

    def _add_plugin(self, plugin: Plugin) -> None:
        if not isinstance(plugin, Plugin):
            raise ValueError(
                "The OTS plugin must be an instance of Plugin"
            )

        logger.info(f"Adding {plugin.name}")
        plugin.load_metadata()
        self.plugins[plugin.distro.lower()] = plugin

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

    def check_if_plugin_enabled(self, plugin_distro: str) -> bool:
        with self._app.app_context():
            plugin = db.session.execute(db.session.query(Plugins).filter_by(name=plugin_distro.lower())).first()
            if plugin:
                return plugin[0].enabled
            else:
                # First time this plugin has been loaded, enable it by default
                return True

    @staticmethod
    @socketio.on('plugin_package_manager', namespace="/socket.io")
    @administrator_only
    def install_plugin(json: dict):
        plugin_valid = json.get('action') == 'install_local'
        file_name = None

        if json.get('action') != "install_local":
            for plugin_prefix in app.config.get("OTS_PLUGIN_PREFIXES"):
                if json.get('plugin_distro').startswith(plugin_prefix):
                    plugin_valid = True
                    break

        if not plugin_valid:
            logger.error(f"Invalid Plugin: {json.get('plugin_distro')}")
            socketio.emit('plugin_package_manager', {"success": False, "message": f"Invalid Plugin: {json.get('plugin_distro')}"}, to=request.sid, namespace="/socket.io")
            return

        if json.get('action') == 'delete':
            command = f"{sys.executable} -m pip uninstall --yes {json.get('plugin_distro')}"
            try:
                logger.info(f"Disabling plugin {json.get('plugin_distro')}")
                app.plugin_manager.disable_plugin(json.get('plugin_distro').lower())
            except BaseException as e:
                logger.error(f"Failed to disable plugin: {e}")
                logger.debug(traceback.format_exc())

        elif json.get('action') == 'install':
            command = f"{sys.executable} -m pip --no-input install {json.get('plugin_distro')} -i {app.config.get('OTS_PLUGIN_REPO')}"

        elif json.get('action') == 'install_local':
            logger.info(f"{json.get('action')} {json.get('plugin_file_name')}")
            file_name = secure_filename(json.get('plugin_file_name'))

            if not os.path.exists(os.path.join(app.config.get('UPLOAD_FOLDER'), file_name)):
                logger.error(f"Plugin file not found: {file_name}")
                socketio.emit('plugin_package_manager', {"success": False, "message": f"Plugin file not found: {file_name}"}, namespace="/socket.io", to=request.sid, ignore_queue=True)
                return

            command = f"{sys.executable} -m pip --no-input install {os.path.join(app.config.get('UPLOAD_FOLDER'), file_name)}"

        else:
            logger.error(f"Invalid action: {json.get('action')}")
            socketio.emit('plugin_package_manager', {"success": False, "message": f"Invalid action: {json.get('action')}"}, namespace="/socket.io", to=request.sid, ignore_queue=True)
            return

        socketio.emit('plugin_package_manager', {"message": f"$ {command}\n"}, namespace="/socket.io", to=request.sid, ignore_queue=True)
        return_code = None

        try:
            output = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
            sel = selectors.DefaultSelector()
            sel.register(output.stdout, selectors.EVENT_READ)
            sel.register(output.stderr, selectors.EVENT_READ)
        except BaseException as e:
            logger.error(f"Failed to run command {command}: {e}")
            logger.error(traceback.format_exc())
            socketio.emit("plugin_package_manager", {"success": False, "message": f"Command failed: {e}"}, namespace="/socket.io", to=request.sid, ignore_queue=True)
            return

        while return_code is None:
            for key, _ in sel.select():
                if key.fileobj != output.stdin:
                    data = key.fileobj.read1().decode()

                    if data:
                        socketio.emit('plugin_package_manager', {"message": data}, to=request.sid, namespace="/socket.io", ignore_queue=True)

                return_code = output.poll()
        if return_code == 0:
            socketio.emit('plugin_package_manager', {"success": True, "message": "Command completed successfully"}, to=request.sid, namespace="/socket.io", ignore_queue=True)

            if json.get('action') == 'install':
                entry_points = app.plugin_manager.get_plugin_entry_points()
                for entry_point in entry_points:
                    plugin = entry_point.load()
                    if plugin().distro.lower() == json.get("plugin_distro").lower():
                        app.plugin_manager._add_plugin(plugin())
                        plugin_row = Plugins()
                        plugin_row.name = plugin().name.lower()
                        plugin_row.distro = plugin().distro
                        plugin_row.author = plugin().metadata['author']
                        plugin_row.version = plugin().metadata['version']
                        plugin_row.enabled = True
                        db.session.add(plugin_row)
                        db.session.commit()

                        if json.get('plugin_distro').lower() not in app.plugin_manager.plugins:
                            app.plugin_manager.plugins[json.get('plugin_distro').lower()] = plugin
                        break

                app.plugin_manager.enable_plugin(json.get("plugin_distro").lower())

            elif json.get('action') == 'delete':
                del app.plugin_manager.plugins[json.get('plugin_distro').lower()]
                plugin = db.session.execute(db.session.query(Plugins).filter_by(distro=json.get('plugin_distro').lower())).first()
                if plugin:
                    db.session.delete(plugin[0])
                    db.session.commit()
            else:
                app.plugin_manager.load_plugins()
        else:
            logger.error(f"Action {json.get('action')} failed with exit code: {return_code}")
            socketio.emit('plugin_package_manager', {"success": False, "message": f"Command failed with return code: {return_code}"}, to=request.sid, namespace="/socket.io", ignore_queue=True)

        if json.get('action') == 'install_local' and file_name is not None:
            os.remove(os.path.join(app.config.get('UPLOAD_FOLDER'), file_name))
