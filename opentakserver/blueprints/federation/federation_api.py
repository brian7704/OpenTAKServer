from flask import request, jsonify, current_app as app
from flask_security import auth_required, roles_required
from opentakserver.extensions import db, logger
from opentakserver.models.FederationServer import FederationServer
from opentakserver.models.FederationOutbound import FederationOutbound
from . import federation_blueprint
import json


@federation_blueprint.route('/api/federation/servers', methods=['GET'])
@auth_required()
@roles_required('administrator')
def list_federation_servers():
    """
    List all configured federation servers.

    Returns:
        JSON array of federation server configurations
    """
    try:
        servers = FederationServer.query.all()
        return jsonify({
            'success': True,
            'servers': [server.to_json() for server in servers]
        }), 200
    except Exception as e:
        logger.error(f"Error listing federation servers: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@federation_blueprint.route('/api/federation/servers', methods=['POST'])
@auth_required()
@roles_required('administrator')
def create_federation_server():
    """
    Create a new federation server configuration.

    Required JSON parameters:
        - name: Unique name for the federation server
        - address: IP address or hostname
        - port: Port number (9000 for v1, 9001 for v2)

    Optional JSON parameters:
        - description: Description of the federation server
        - connection_type: "outbound" or "inbound" (default: "outbound")
        - protocol_version: "v1" or "v2" (default: "v2")
        - transport_protocol: "tcp", "udp", or "multicast" (default: "tcp")
        - use_tls: Boolean (default: true)
        - verify_ssl: Boolean (default: true)
        - ca_certificate: Remote server's CA certificate (PEM format)
        - client_certificate: Our client certificate for outbound connections
        - client_key: Our client key for outbound connections
        - sync_missions: Boolean (default: true)
        - sync_cot: Boolean (default: true)
        - mission_filter: JSON array of mission names to sync
        - enabled: Boolean (default: true)

    Returns:
        JSON with the created server configuration
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        # Validate required fields
        required_fields = ['name', 'address', 'port']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400

        # Check if name already exists
        existing = FederationServer.query.filter_by(name=data['name']).first()
        if existing:
            return jsonify({'success': False, 'error': 'Federation server with this name already exists'}), 409

        # Validate connection type
        connection_type = data.get('connection_type', FederationServer.OUTBOUND)
        if connection_type not in [FederationServer.OUTBOUND, FederationServer.INBOUND]:
            return jsonify({'success': False, 'error': 'Invalid connection_type. Must be "outbound" or "inbound"'}), 400

        # Validate protocol version
        protocol_version = data.get('protocol_version', FederationServer.FEDERATION_V2)
        if protocol_version not in [FederationServer.FEDERATION_V1, FederationServer.FEDERATION_V2]:
            return jsonify({'success': False, 'error': 'Invalid protocol_version. Must be "v1" or "v2"'}), 400

        # Validate transport protocol
        transport_protocol = data.get('transport_protocol', FederationServer.TRANSPORT_TCP)
        if transport_protocol not in [FederationServer.TRANSPORT_TCP, FederationServer.TRANSPORT_UDP, FederationServer.TRANSPORT_MULTICAST]:
            return jsonify({'success': False, 'error': 'Invalid transport_protocol. Must be "tcp", "udp", or "multicast"'}), 400

        # Create federation server
        server = FederationServer(
            name=data['name'],
            description=data.get('description'),
            address=data['address'],
            port=data['port'],
            connection_type=connection_type,
            protocol_version=protocol_version,
            transport_protocol=transport_protocol,
            use_tls=data.get('use_tls', True),
            verify_ssl=data.get('verify_ssl', True),
            ca_certificate=data.get('ca_certificate'),
            client_certificate=data.get('client_certificate'),
            client_key=data.get('client_key'),
            sync_missions=data.get('sync_missions', True),
            sync_cot=data.get('sync_cot', True),
            mission_filter=json.dumps(data['mission_filter']) if 'mission_filter' in data else None,
            enabled=data.get('enabled', True)
        )

        db.session.add(server)
        db.session.commit()

        logger.info(f"Created federation server: {server.name}")

        return jsonify({
            'success': True,
            'server': server.to_json()
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating federation server: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@federation_blueprint.route('/api/federation/servers/<int:server_id>', methods=['GET'])
@auth_required()
@roles_required('administrator')
def get_federation_server(server_id):
    """Get a specific federation server by ID"""
    try:
        server = FederationServer.query.get(server_id)
        if not server:
            return jsonify({'success': False, 'error': 'Federation server not found'}), 404

        return jsonify({
            'success': True,
            'server': server.to_json()
        }), 200

    except Exception as e:
        logger.error(f"Error getting federation server: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@federation_blueprint.route('/api/federation/servers/<int:server_id>', methods=['PUT'])
@auth_required()
@roles_required('administrator')
def update_federation_server(server_id):
    """Update a federation server configuration"""
    try:
        server = FederationServer.query.get(server_id)
        if not server:
            return jsonify({'success': False, 'error': 'Federation server not found'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        # Update fields
        updateable_fields = [
            'name', 'description', 'address', 'port', 'connection_type', 'protocol_version',
            'transport_protocol', 'use_tls', 'verify_ssl', 'ca_certificate', 'client_certificate',
            'client_key', 'sync_missions', 'sync_cot', 'mission_filter', 'enabled'
        ]

        for field in updateable_fields:
            if field in data:
                if field == 'mission_filter' and data[field] is not None:
                    setattr(server, field, json.dumps(data[field]))
                else:
                    setattr(server, field, data[field])

        db.session.commit()

        logger.info(f"Updated federation server: {server.name}")

        return jsonify({
            'success': True,
            'server': server.to_json()
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating federation server: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@federation_blueprint.route('/api/federation/servers/<int:server_id>', methods=['DELETE'])
@auth_required()
@roles_required('administrator')
def delete_federation_server(server_id):
    """Delete a federation server configuration"""
    try:
        server = FederationServer.query.get(server_id)
        if not server:
            return jsonify({'success': False, 'error': 'Federation server not found'}), 404

        server_name = server.name
        db.session.delete(server)
        db.session.commit()

        logger.info(f"Deleted federation server: {server_name}")

        return jsonify({
            'success': True,
            'message': f'Federation server {server_name} deleted'
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting federation server: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@federation_blueprint.route('/api/federation/servers/<int:server_id>/status', methods=['GET'])
@auth_required()
@roles_required('administrator')
def get_federation_server_status(server_id):
    """
    Get the status and synchronization statistics for a federation server.

    Returns:
        JSON with server status and stats
    """
    try:
        server = FederationServer.query.get(server_id)
        if not server:
            return jsonify({'success': False, 'error': 'Federation server not found'}), 404

        # Get synchronization statistics
        total_changes = FederationOutbound.query.filter_by(federation_server_id=server_id).count()
        sent_changes = FederationOutbound.query.filter_by(federation_server_id=server_id, sent=True).count()
        pending_changes = total_changes - sent_changes

        return jsonify({
            'success': True,
            'status': {
                'server': server.to_json(),
                'stats': {
                    'total_changes': total_changes,
                    'sent_changes': sent_changes,
                    'pending_changes': pending_changes
                }
            }
        }), 200

    except Exception as e:
        logger.error(f"Error getting federation server status: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@federation_blueprint.route('/api/federation/servers/<int:server_id>/test', methods=['POST'])
@auth_required()
@roles_required('administrator')
def test_federation_connection(server_id):
    """
    Test the connection to a federation server.

    This endpoint attempts to establish a connection to verify configuration.

    Returns:
        JSON with test results
    """
    try:
        from flask import current_app
        from opentakserver.blueprints.federation.federation_service import FederationConnection
        import time

        server = FederationServer.query.get(server_id)
        if not server:
            return jsonify({'success': False, 'error': 'Federation server not found'}), 404

        # Attempt to create a test connection
        logger.info(f"Testing connection to federation server: {server.name}")
        test_conn = FederationConnection(server, current_app.config)

        # Try to connect (with a timeout)
        start_time = time.time()
        success = test_conn.connect()
        elapsed = time.time() - start_time

        # Disconnect immediately
        if success:
            test_conn.disconnect()

            return jsonify({
                'success': True,
                'message': f'Successfully connected to {server.name} via {server.transport_protocol.upper()}',
                'connection_time_ms': round(elapsed * 1000, 2),
                'transport_protocol': server.transport_protocol,
                'server': server.to_json()
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to connect to {server.name}. Check logs for details.',
                'server': server.to_json()
            }), 503

    except Exception as e:
        logger.error(f"Error testing federation connection: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e),
            'details': 'Connection test failed with exception'
        }), 500


@federation_blueprint.route('/api/federation/health', methods=['GET'])
@auth_required()
def federation_health():
    """
    Get overall federation health status.

    Returns:
        JSON with federation system status
    """
    try:
        total_servers = FederationServer.query.count()
        enabled_servers = FederationServer.query.filter_by(enabled=True).count()
        connected_servers = FederationServer.query.filter_by(
            enabled=True,
            status=FederationServer.STATUS_CONNECTED
        ).count()

        return jsonify({
            'success': True,
            'health': {
                'federation_enabled': app.config.get('OTS_ENABLE_FEDERATION', False),
                'total_servers': total_servers,
                'enabled_servers': enabled_servers,
                'connected_servers': connected_servers,
                'node_id': app.config.get('OTS_NODE_ID')
            }
        }), 200

    except Exception as e:
        logger.error(f"Error getting federation health: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
