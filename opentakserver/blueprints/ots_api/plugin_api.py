import traceback

from flask import Blueprint, request, jsonify
from flask_security import roles_required

from opentakserver.plugins.Plugin import Plugin
from opentakserver.plugins.PluginManager import PluginManager
from opentakserver.extensions import logger

plugin_blueprint = Blueprint("plugin_api_blueprint", __name__)


@plugin_blueprint.route("/api/plugins")
@roles_required("administrator")
def get_plugins():
    plugin_manager = PluginManager(Plugin.group, plugin_blueprint)
    plugin_manager.load_plugins()
    return jsonify({'success': True, 'plugins': plugin_manager._plugins.values()})


@plugin_blueprint.route("/api/plugins/<plugin_distro>/disable")
@roles_required("administrator")
def disable_plugin(plugin_distro):
    try:
        plugin_manager = PluginManager(Plugin.group, plugin_blueprint)
        plugin_manager.load_plugins()
        plugin_manager.disable_plugin(plugin_distro)
        return jsonify({'success': True})
    except BaseException as e:
        logger.error(f"Failed to disable {plugin_distro}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)})


@plugin_blueprint.route("/api/plugins/<plugin_distro>/enable")
@roles_required("administrator")
def enable_plugin(plugin_distro):
    try:
        plugin_manager = PluginManager(Plugin.group, plugin_blueprint)
        plugin_manager.load_plugins()
        plugin_manager.enable_plugin(plugin_distro)
        return jsonify({'success': True})
    except BaseException as e:
        logger.error(f"Failed to enable {plugin_distro}: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)})