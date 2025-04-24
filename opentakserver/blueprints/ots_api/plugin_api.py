import traceback

from flask import Blueprint, request, jsonify, current_app as app
from flask_security import roles_required

from opentakserver.plugins.Plugin import Plugin
from opentakserver.plugins.PluginManager import PluginManager
from opentakserver.extensions import logger

plugin_blueprint = Blueprint("plugin_api_blueprint", __name__)


@plugin_blueprint.route("/api/plugins")
@roles_required("administrator")
def get_plugins():
    if hasattr(app, 'plugin_manager'):
        plugins = []

        for plugin in app.plugin_manager._plugins.values():
            plugins.append(plugin.get_info())

        return jsonify({'success': True, 'plugins': plugins})
    else:
        return jsonify({'success': True, 'plugins': []}), 200


@plugin_blueprint.route("/api/plugins/<plugin_distro>/disable", methods=["POST"])
@roles_required("administrator")
def disable_plugin(plugin_distro):
    if hasattr(app, 'plugin_manager'):
        try:
            logger.info(f"Disabling plugin {plugin_distro}")
            app.plugin_manager.disable_plugin(plugin_distro)
            return jsonify({'success': True})
        except BaseException as e:
            logger.error(f"Failed to disable {plugin_distro}: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)})
    else:
        return jsonify({'success': False, 'error': 'Plugins are disabled'}), 400


@plugin_blueprint.route("/api/plugins/<plugin_distro>/enable", methods=["POST"])
@roles_required("administrator")
def enable_plugin(plugin_distro):
    if hasattr(app, 'plugin_manager'):
        try:
            app.plugin_manager.enable_plugin(plugin_distro)
            return jsonify({'success': True})
        except BaseException as e:
            logger.error(f"Failed to enable {plugin_distro}: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)})
    else:
        return jsonify({'success': False, 'error': 'Plugins are disabled'}), 400
