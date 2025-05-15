import traceback

from flask import Blueprint, jsonify, current_app as app
from flask_security import roles_required

from opentakserver.extensions import logger

plugin_blueprint = Blueprint("plugin_api_blueprint", __name__)


@plugin_blueprint.route("/api/plugins")
@roles_required("administrator")
def get_plugins():
    if hasattr(app, 'plugin_manager'):
        plugins = []

        for plugin in app.plugin_manager.plugins.values():
            plugins.append(plugin.get_info())

        return jsonify({'success': True, 'plugins': plugins})
    else:
        return jsonify({'success': True, 'plugins': []}), 200


@plugin_blueprint.route("/api/plugins/<plugin_name>", strict_slashes=False)
@roles_required("administrator")
def get_plugin(plugin_name: str):
    if hasattr(app, 'plugin_manager'):
        plugin = app.plugin_manager.plugins.get(plugin_name)
        if plugin:
            plugin_metadata = plugin.load_metadata()
            plugin_metadata['enabled'] = app.plugin_manager.check_if_plugin_enabled(plugin.name.lower())
            return jsonify(plugin_metadata)
        else:
            return jsonify({'success': False, 'error': f'Plugin {plugin_name} not found'}), 404
    else:
        return jsonify({'success': False, 'error': 'Plugins are disabled'}), 400


@plugin_blueprint.route("/api/plugins/<plugin_name>/disable", methods=["POST"])
@roles_required("administrator")
def disable_plugin(plugin_name):
    if hasattr(app, 'plugin_manager'):
        try:
            logger.info(f"Disabling plugin {plugin_name}")
            app.plugin_manager.disable_plugin(plugin_name)
            return jsonify({'success': True})
        except BaseException as e:
            logger.error(f"Failed to disable {plugin_name}: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)})
    else:
        return jsonify({'success': False, 'error': 'Plugins are disabled'}), 400


@plugin_blueprint.route("/api/plugins/<plugin_name>/enable", methods=["POST"])
@roles_required("administrator")
def enable_plugin(plugin_name):
    if hasattr(app, 'plugin_manager'):
        try:
            app.plugin_manager.enable_plugin(plugin_name)
            return jsonify({'success': True})
        except BaseException as e:
            logger.error(f"Failed to enable {plugin_name}: {e}")
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)})
    else:
        return jsonify({'success': False, 'error': 'Plugins are disabled'}), 400
