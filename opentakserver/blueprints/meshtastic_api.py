import base64
import os
import traceback

from meshtastic import channel_pb2, apponly_pb2, config_pb2

import bleach
from flask import Blueprint, request, jsonify
from flask_security import auth_required

from opentakserver.extensions import logger, db
from opentakserver.models.Meshtastic import MeshtasticChannelSettings
from opentakserver.blueprints.api import paginate, search

meshtastic_api_blueprint = Blueprint("meshtastic_api_blueprint", __name__)


@meshtastic_api_blueprint.route("/api/meshtastic/channel", methods=['POST'])
@auth_required()
def create_channel():
    channel_set = apponly_pb2.ChannelSet()
    channel_settings = channel_pb2.ChannelSettings()

    # Parse the settings from a Meshtastic URL
    if 'url' in request.json.keys() and request.json.get('url'):
        try:
            settings = base64.b64decode(bleach.clean(request.json.get('url').split("#")[-1]) + "==")
            channel_set.ParseFromString(settings)
            url = request.json.get('url')
            channel_settings = channel_set.settings[0]

        except BaseException as e:
            logger.error("Failed to parse Meshtastic  URL: {}".format(e))
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)}), 400

    # Make the protobuf from settings in order to make the URL
    else:
        try:
            channel_set.lora_config.use_preset = True
            channel_set.lora_config.modem_preset = bleach.clean(request.json.get('modem_preset')) if request.json.get('modem_preset') else None
            channel_set.lora_config.region = bleach.clean(request.json.get('lora_region')) if request.json.get('lora_region') else None
            channel_set.lora_config.hop_limit = request.json.get('lora_hop_limit') if request.json.get('lora_hop_limit') else None
            channel_set.lora_config.tx_enabled = request.json.get('lora_tx_enabled')
            channel_set.lora_config.tx_power = request.json.get('lora_tx_power') if request.json.get('lora_tx_power') else None
            channel_set.lora_config.sx126x_rx_boosted_gain = request.json.get('lora_sx126x_rx_boosted_gain')

            if 'psk' in request.json.keys() and request.json.get('psk'):
                channel_settings.psk = base64.b64decode(bleach.clean(request.json.get('psk')))
            else:
                # Zero bytes indicates no encryption
                channel_settings.psk = bytes(0)
            channel_settings.name = bleach.clean(request.json.get('name')) if request.json.get('name') else None
            channel_settings.uplink_enabled = request.json.get('uplink_enabled')
            channel_settings.downlink_enabled = request.json.get('downlink_enabled')
            channel_settings.module_settings.position_precision = request.json.get('position_precision') if request.json.get('position_precision') else None

            channel_set.settings.append(channel_settings)

            url = "https://meshtastic.org/e/#" + base64.b64encode(channel_set.SerializeToString()).decode('utf-8')

        except BaseException as e:
            logger.error("Failed to save Meshtastic channel: {}".format(e))
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'error': str(e)}), 400

    meshtastic_channel_settings = MeshtasticChannelSettings()
    meshtastic_channel_settings.psk = base64.b64encode(channel_settings.psk).decode('ascii')
    meshtastic_channel_settings.name = channel_settings.name
    meshtastic_channel_settings.uplink_enabled = channel_settings.uplink_enabled
    meshtastic_channel_settings.downlink_enabled = channel_settings.downlink_enabled
    meshtastic_channel_settings.position_precision = channel_settings.module_settings.position_precision
    meshtastic_channel_settings.lora_region = channel_set.lora_config.region
    meshtastic_channel_settings.lora_hop_limit = channel_set.lora_config.hop_limit
    meshtastic_channel_settings.lora_tx_enabled = channel_set.lora_config.tx_enabled
    meshtastic_channel_settings.lora_tx_power = channel_set.lora_config.tx_power
    meshtastic_channel_settings.lora_sx126x_rx_boosted_gain = channel_set.lora_config.sx126x_rx_boosted_gain
    meshtastic_channel_settings.modem_preset = channel_set.lora_config.modem_preset
    meshtastic_channel_settings.url = url

    db.session.add(meshtastic_channel_settings)
    db.session.commit()

    return jsonify({'success': True, 'url': url})


@meshtastic_api_blueprint.route("/api/meshtastic/channel", methods=['GET'])
@auth_required()
def get_channel():
    query = db.session.query(MeshtasticChannelSettings)
    query = search(query, MeshtasticChannelSettings, 'id')
    query = search(query, MeshtasticChannelSettings, 'name')
    query = search(query, MeshtasticChannelSettings, 'url')

    return paginate(query)


@meshtastic_api_blueprint.route("/api/meshtastic/channel", methods=['DELETE'])
@auth_required()
def delete_channel():
    pass


@meshtastic_api_blueprint.route("/api/meshtastic/generate_psk")
@auth_required()
def generate_psk():
    return jsonify({"success": True, "psk": base64.b64encode(os.urandom(32)).decode('ascii')}), 200
