"""
Federation Service

This service handles:
1. Outbound connections to federated TAK servers
2. Inbound connections from federated TAK servers
3. Mission change synchronization
4. CoT message federation
5. Connection health monitoring and retry logic

Transport Protocol Support:
- TCP: Stream-based transport with TLS encryption (default, recommended)
- UDP: Datagram-based transport (currently unencrypted - DTLS not implemented)

DTLS Limitation:
UDP connections are currently unencrypted. DTLS (Datagram TLS) support requires
additional dependencies (e.g., PyDTLS) which are not currently available.
For production use with sensitive data, TCP with TLS is recommended.

UDP-Specific Considerations:
- Connectionless: UDP does not establish a persistent connection
- Unreliable: Packets may be lost, duplicated, or arrive out of order
- MTU Limited: Each CoT message must fit within the MTU (typically 1500 bytes)
- No Flow Control: Application must handle rate limiting
"""

import ssl
import socket
import threading
import time
import json
import tempfile
import os
import uuid
import struct
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import tostring, Element
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from opentakserver.extensions import db, logger
from opentakserver.models.FederationServer import FederationServer
from opentakserver.models.FederationOutbound import FederationOutbound
from opentakserver.models.MissionChange import MissionChange, generate_mission_change_cot
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionContent import MissionContent
from opentakserver.models.MissionUID import MissionUID

# Maximum UDP datagram size (accounting for IP/UDP headers)
# Conservative size to avoid fragmentation: 1500 (Ethernet MTU) - 20 (IP) - 8 (UDP) = 1472
# But TAK typically uses larger buffers, so we'll use 8192 and log warnings for oversized messages
MAX_UDP_DATAGRAM_SIZE = 8192
SAFE_UDP_SIZE = 1400  # Safe size to avoid fragmentation


class FederationConnection:
    """
    Represents an active connection to a federated server.

    Handles:
    - TCP/UDP socket connections
    - TLS encryption (TCP only, DTLS not currently supported for UDP)
    - Message sending/receiving
    - Heartbeat/keepalive (TCP only)
    - Reconnection logic
    """

    def __init__(self, federation_server: FederationServer, app_config, is_inbound: bool = False,
                 wrapped_socket: Optional[socket.socket] = None):
        """
        Initialize a federation connection.

        Args:
            federation_server: FederationServer database object
            app_config: Application configuration dict
            is_inbound: True if this is an inbound connection (remote connected to us)
            wrapped_socket: Already-connected socket (for inbound connections)
        """
        self.federation_server = federation_server
        self.app_config = app_config
        self.is_inbound = is_inbound
        self.socket: Optional[socket.socket] = wrapped_socket
        self.connected = bool(wrapped_socket)  # If socket provided, we're already connected
        self.running = False
        self.send_thread: Optional[threading.Thread] = None
        self.receive_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        # Temporary certificate files (cleaned up on disconnect)
        self.temp_ca_file: Optional[str] = None
        self.temp_cert_file: Optional[str] = None
        self.temp_key_file: Optional[str] = None
        # Remote address for UDP (stored for connectionless communication)
        self.remote_addr: Optional[Tuple[str, int]] = None

        # Check if using UDP transport
        self.is_udp = self.federation_server.transport_protocol == FederationServer.TRANSPORT_UDP

        # Warn about UDP encryption limitation
        if self.is_udp and self.federation_server.use_tls:
            logger.warning(
                f"DTLS is not currently supported for UDP federation. "
                f"Connection to {self.federation_server.name} will be UNENCRYPTED. "
                f"For encrypted federation, use TCP transport protocol."
            )

    def connect(self) -> bool:
        """
        Establish connection to the federated server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"Connecting to federation server: {self.federation_server.name} "
                       f"({self.federation_server.address}:{self.federation_server.port}) "
                       f"via {self.federation_server.transport_protocol.upper()}")

            # Branch based on transport protocol
            if self.is_udp:
                return self._connect_udp()

            # TCP connection
            raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_socket.settimeout(30)

            # Wrap with TLS if enabled
            if self.federation_server.use_tls:
                context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

                # Load CA certificate if provided
                if self.federation_server.ca_certificate:
                    # Write CA cert to secure temp file
                    fd, self.temp_ca_file = tempfile.mkstemp(suffix='.crt', text=True)
                    try:
                        os.write(fd, self.federation_server.ca_certificate.encode('utf-8'))
                        os.close(fd)
                        context.load_verify_locations(cafile=self.temp_ca_file)
                        logger.debug(f"Loaded CA certificate for {self.federation_server.name}")
                    except Exception as e:
                        logger.error(f"Failed to load CA certificate: {e}")
                        os.close(fd)
                        raise

                # Load client certificate and key for mutual TLS
                if self.federation_server.client_certificate and self.federation_server.client_key:
                    # Write cert and key to secure temp files
                    cert_fd, self.temp_cert_file = tempfile.mkstemp(suffix='.crt', text=True)
                    key_fd, self.temp_key_file = tempfile.mkstemp(suffix='.key', text=True)
                    try:
                        os.write(cert_fd, self.federation_server.client_certificate.encode('utf-8'))
                        os.close(cert_fd)
                        os.write(key_fd, self.federation_server.client_key.encode('utf-8'))
                        os.close(key_fd)
                        # Set restrictive permissions on key file
                        os.chmod(self.temp_key_file, 0o600)
                        context.load_cert_chain(certfile=self.temp_cert_file, keyfile=self.temp_key_file)
                        logger.debug(f"Loaded client certificate for {self.federation_server.name}")
                    except Exception as e:
                        logger.error(f"Failed to load client certificate: {e}")
                        os.close(cert_fd)
                        os.close(key_fd)
                        raise

                # Disable SSL verification if configured
                if not self.federation_server.verify_ssl:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE

                self.socket = context.wrap_socket(
                    raw_socket,
                    server_hostname=self.federation_server.address
                )
            else:
                self.socket = raw_socket

            # Connect
            self.socket.connect((self.federation_server.address, self.federation_server.port))
            self.connected = True
            self.running = True

            # Update database status
            with db.session.begin():
                server = db.session.query(FederationServer).get(self.federation_server.id)
                server.status = FederationServer.STATUS_CONNECTED
                server.last_connected = datetime.utcnow()
                server.last_error = None

            logger.info(f"Successfully connected to federation server: {self.federation_server.name}")

            # Start threads
            self.start_threads()

            return True

        except Exception as e:
            logger.error(f"Failed to connect to federation server {self.federation_server.name}: {e}",
                        exc_info=True)

            # Clean up any temp files that may have been created
            self._cleanup_temp_files()

            # Update database status
            try:
                with db.session.begin():
                    server = db.session.query(FederationServer).get(self.federation_server.id)
                    server.status = FederationServer.STATUS_ERROR
                    server.last_error = str(e)
            except Exception as db_error:
                logger.error(f"Failed to update federation server status: {db_error}", exc_info=True)

            self.connected = False
            return False


    def _connect_udp(self) -> bool:
        """
        Establish UDP socket (connectionless).
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.settimeout(30)

            # Store remote address for sending
            self.remote_addr = (self.federation_server.address, self.federation_server.port)

            # For UDP, we can optionally call connect() to bind the socket to the remote address
            # This allows us to use send() instead of sendto()
            try:
                self.socket.connect(self.remote_addr)
                logger.debug(f"Bound UDP socket to {self.remote_addr}")
            except Exception as e:
                logger.warning(f"Could not bind UDP socket to {self.remote_addr}: {e}. Will use sendto() instead.")

            self.connected = True
            self.running = True

            # Update database status
            with db.session.begin():
                server = db.session.query(FederationServer).get(self.federation_server.id)
                server.status = FederationServer.STATUS_CONNECTED
                server.last_connected = datetime.utcnow()
                server.last_error = None

            logger.info(f"Successfully initialized UDP socket for federation server: {self.federation_server.name}")

            # Start threads (no heartbeat for UDP)
            self.start_threads()

            return True

        except Exception as e:
            logger.error(f"Failed to initialize UDP socket: {e}", exc_info=True)
            return False

    def disconnect(self):
        """Disconnect from the federated server"""
        logger.info(f"Disconnecting from federation server: {self.federation_server.name}")

        self.running = False
        self.connected = False

        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"Error closing socket: {e}")

        # Wait for threads to finish
        if self.send_thread and self.send_thread.is_alive():
            self.send_thread.join(timeout=5)
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=5)
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.heartbeat_thread.join(timeout=5)

        # Clean up temporary certificate files
        self._cleanup_temp_files()

        # Update database status
        try:
            with db.session.begin():
                server = db.session.query(FederationServer).get(self.federation_server.id)
                server.status = FederationServer.STATUS_DISCONNECTED
        except Exception as e:
            logger.error(f"Failed to update federation server status: {e}", exc_info=True)

    def _cleanup_temp_files(self):
        """Clean up temporary certificate files"""
        for temp_file in [self.temp_ca_file, self.temp_cert_file, self.temp_key_file]:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    logger.debug(f"Removed temporary file: {temp_file}")
                except Exception as e:
                    logger.error(f"Failed to remove temporary file {temp_file}: {e}")

        self.temp_ca_file = None
        self.temp_cert_file = None
        self.temp_key_file = None

    def start_threads(self):
        """Start background threads for sending, receiving, and heartbeat"""
        self.send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)

        self.send_thread.start()
        self.receive_thread.start()

        # Only start heartbeat for TCP connections (UDP is connectionless)
        if not self.is_udp:
            self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self.heartbeat_thread.start()


    def _send_message_tcp(self, data: bytes):
        """Send data via TCP stream."""
        self.socket.sendall(data)

    def _send_message_udp(self, data: bytes):
        """
        Send data via UDP datagram.
        
        Args:
            data: Raw bytes to send
            
        Raises:
            ValueError: If message exceeds safe UDP size
        """
        if len(data) > MAX_UDP_DATAGRAM_SIZE:
            raise ValueError(
                f"Message size ({len(data)} bytes) exceeds maximum UDP datagram size "
                f"({MAX_UDP_DATAGRAM_SIZE} bytes). Message will be truncated or dropped."
            )

        if len(data) > SAFE_UDP_SIZE:
            logger.warning(
                f"UDP message size ({len(data)} bytes) exceeds safe size ({SAFE_UDP_SIZE} bytes). "
                f"Message may be fragmented and could be dropped."
            )

        # Try to use send() if socket was connect()ed, otherwise use sendto()
        try:
            self.socket.send(data)
        except OSError:
            # Socket not connected, use sendto()
            if self.remote_addr:
                self.socket.sendto(data, self.remote_addr)
            else:
                raise ValueError("No remote address configured for UDP connection")

    def _send_loop(self):
        """
        Background thread that sends pending mission changes to the federated server.

        Implements Mission Federation Disruption Tolerance by retrying failed sends.
        """
        logger.info(f"Starting send loop for federation server: {self.federation_server.name}")

        while self.running and self.connected:
            try:
                # Query for pending mission changes that need to be sent
                with db.session.begin():
                    pending = db.session.query(FederationOutbound).filter_by(
                        federation_server_id=self.federation_server.id,
                        sent=False
                    ).filter(
                        (FederationOutbound.retry_count < self.app_config.get('OTS_FEDERATION_MAX_RETRIES', 5))
                    ).limit(10).all()

                    for outbound in pending:
                        try:
                            # Get the mission change
                            mission_change = outbound.mission_change
                            mission = mission_change.mission

                            # Generate CoT for this change
                            cot_element = generate_mission_change_cot(
                                author_uid=mission_change.creator_uid,
                                mission=mission,
                                mission_change=mission_change,
                                content=mission_change.content_resource,
                                mission_uid=mission_change.uid
                            )

                            # Convert to XML string
                            cot_xml = tostring(cot_element, encoding='utf-8')

                            # Send via appropriate transport
                            if self.is_udp:
                                self._send_message_udp(cot_xml)
                            else:
                                self._send_message_tcp(cot_xml)

                            # Update outbound record
                            outbound.sent = True
                            outbound.sent_at = datetime.utcnow()
                            outbound.last_error = None

                            logger.debug(f"Sent mission change {mission_change.id} to {self.federation_server.name}")

                        except Exception as e:
                            logger.error(f"Error sending mission change {outbound.mission_change_id}: {e}",
                                       exc_info=True)
                            outbound.retry_count += 1
                            outbound.last_retry_at = datetime.utcnow()
                            outbound.last_error = str(e)[:1000]  # Truncate to fit in DB

                # Sleep before checking for more changes
                time.sleep(5)

            except Exception as e:
                logger.error(f"Error in send loop for {self.federation_server.name}: {e}", exc_info=True)
                time.sleep(10)

        logger.info(f"Send loop stopped for federation server: {self.federation_server.name}")

    def _receive_loop(self):
        """
        Background thread that receives mission changes from the federated server.

        Processes incoming CoT messages and creates mission changes marked as federated.
        Handles both TCP (stream) and UDP (datagram) transports.
        """
        logger.info(f"Starting receive loop for federation server: {self.federation_server.name}")

        if self.is_udp:
            self._receive_loop_udp()
        else:
            self._receive_loop_tcp()

        logger.info(f"Receive loop stopped for federation server: {self.federation_server.name}")

    def _receive_loop_tcp(self):
        """TCP receive loop - handles stream data with buffering"""
        buffer = b""

        while self.running and self.connected:
            try:
                # Receive data
                data = self.socket.recv(8192)
                if not data:
                    logger.warning(f"Connection closed by {self.federation_server.name}")
                    self.connected = False
                    break

                buffer += data

                # Process complete CoT messages
                # TAK CoT messages are XML and end with </event>
                while b"</event>" in buffer:
                    end_idx = buffer.find(b"</event>") + len(b"</event>")
                    cot_message = buffer[:end_idx]
                    buffer = buffer[end_idx:]

                    # Process the CoT message
                    self._process_federated_cot(cot_message)

            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Error in receive loop for {self.federation_server.name}: {e}", exc_info=True)
                self.connected = False
                break


    def _receive_loop_udp(self):
        """UDP receive loop - handles discrete datagrams"""
        while self.running and self.connected:
            try:
                # Receive datagram - each CoT message should be a complete datagram
                data, addr = self.socket.recvfrom(MAX_UDP_DATAGRAM_SIZE)

                if not data:
                    continue

                # Update remote address from first received packet
                if not self.remote_addr:
                    self.remote_addr = addr
                    logger.debug(f"Set remote address to {addr} from first UDP packet")

                # Process the CoT message (should be complete in one datagram)
                if b"<event" in data and b"</event>" in data:
                    self._process_federated_cot(data)
                else:
                    logger.warning(
                        f"Received incomplete or fragmented UDP datagram from {addr} "
                        f"({len(data)} bytes). CoT message may be too large for UDP."
                    )

            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Error in UDP receive loop for {self.federation_server.name}: {e}", exc_info=True)
                # For UDP, we don't mark as disconnected on receive errors since it's connectionless
                time.sleep(1)

    def _heartbeat_loop(self):
        """
        Background thread that sends periodic heartbeat messages to keep the connection alive.
        """
        logger.info(f"Starting heartbeat loop for federation server: {self.federation_server.name}")

        interval = self.app_config.get('OTS_FEDERATION_HEARTBEAT_INTERVAL', 30)

        while self.running and self.connected:
            try:
                # Create and send TAK heartbeat/ping message
                heartbeat_cot = self._create_heartbeat_cot()
                self.socket.sendall(heartbeat_cot.encode('utf-8'))
                logger.debug(f"Sent heartbeat to {self.federation_server.name}")

                time.sleep(interval)

            except Exception as e:
                logger.error(f"Error in heartbeat loop for {self.federation_server.name}: {e}", exc_info=True)
                # If we can't send heartbeat, connection is probably broken
                self.connected = False
                break

        logger.info(f"Heartbeat loop stopped for federation server: {self.federation_server.name}")

    def _create_heartbeat_cot(self) -> str:
        """
        Create a TAK heartbeat/ping CoT message.

        Returns:
            XML string representing a TAK heartbeat message
        """
        # Get node ID from config or use federation server name
        node_id = self.app_config.get('OTS_NODE_ID', self.federation_server.name)

        # Create heartbeat event
        now = datetime.now(timezone.utc)
        stale_time = now + timedelta(seconds=self.app_config.get('OTS_FEDERATION_HEARTBEAT_INTERVAL', 30) * 2)

        event = Element('event')
        event.set('version', '2.0')
        event.set('uid', f"{node_id}-ping")
        event.set('type', 't-x-c-t')  # TAK Contact
        event.set('time', now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'))
        event.set('start', now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'))
        event.set('stale', stale_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ'))
        event.set('how', 'h-g-i-g-o')  # Generated

        # Add point element (required)
        point = Element('point')
        point.set('lat', '0.0')
        point.set('lon', '0.0')
        point.set('hae', '0.0')
        point.set('ce', '9999999.0')
        point.set('le', '9999999.0')
        event.append(point)

        # Add detail element with contact info
        detail = Element('detail')

        contact = Element('contact')
        contact.set('callsign', f"OTS-{node_id}")
        detail.append(contact)

        # Add takv element (TAK version info)
        takv = Element('takv')
        takv.set('platform', 'OpenTAKServer')
        takv.set('version', self.app_config.get('OTS_VERSION', '1.0.0'))
        takv.set('device', 'federation-server')
        takv.set('os', 'Linux')
        detail.append(takv)

        event.append(detail)

        # Convert to XML string
        xml_str = tostring(event, encoding='unicode')

        return xml_str

    def _process_federated_cot(self, cot_xml: bytes):
        """
        Process an incoming CoT message from a federated server.

        Args:
            cot_xml: Raw CoT XML message
        """
        try:
            # Parse XML
            root = ET.fromstring(cot_xml.decode('utf-8'))

            # Check if this is a mission-related CoT (type starts with t-x-m-)
            cot_type = root.get('type', '')

            # Skip heartbeat and non-mission CoT messages
            if cot_type.startswith('t-x-c-t') or cot_type.startswith('a-'):
                logger.debug(f"Skipping non-mission CoT type: {cot_type}")
                return

            # Look for mission details in the detail element
            detail = root.find('detail')
            if detail is None:
                logger.debug(f"No detail element in CoT, skipping")
                return

            mission_elem = detail.find('mission')
            if mission_elem is None:
                logger.debug(f"No mission element in CoT, skipping")
                return

            # Extract mission information
            mission_name = mission_elem.get('name')
            mission_guid = mission_elem.get('guid')
            author_uid = mission_elem.get('authorUid', root.get('uid'))

            if not mission_name:
                logger.warning(f"Mission element has no name, skipping")
                return

            # Find or create the mission
            with db.session.begin():
                mission = db.session.query(Mission).filter_by(name=mission_name).first()
                if not mission:
                    # Create new mission if it doesn't exist
                    logger.info(f"Creating new mission from federation: {mission_name}")
                    mission = Mission(
                        name=mission_name,
                        guid=mission_guid or str(uuid.uuid4()),
                        creator_uid=author_uid,
                        created=datetime.utcnow()
                    )
                    db.session.add(mission)
                    db.session.flush()  # Get the mission ID

                # Look for MissionChanges element
                mission_changes_elem = mission_elem.find('MissionChanges')
                if mission_changes_elem is not None:
                    for change_elem in mission_changes_elem.findall('MissionChange'):
                        self._process_mission_change(
                            root, mission, change_elem, author_uid
                        )
                else:
                    # If no explicit MissionChanges, treat as a general mission update
                    logger.debug(f"Received mission update from federation: {mission_name}")

            logger.debug(f"Processed federated CoT for mission: {mission_name}")

        except ET.ParseError as e:
            logger.error(f"Failed to parse CoT XML from {self.federation_server.name}: {e}")
        except Exception as e:
            logger.error(f"Error processing federated CoT: {e}", exc_info=True)

    def _process_mission_change(self, cot_root, mission: Mission, change_elem, author_uid: str):
        """
        Process a single mission change from federated CoT.

        Args:
            cot_root: Root XML element of the CoT message
            mission: Mission object
            change_elem: MissionChange XML element
            author_uid: UID of the change author
        """
        try:
            # Extract change type
            change_type = change_elem.get('type', MissionChange.CHANGE)

            # Get timestamp from CoT root
            timestamp_str = cot_root.get('time')
            if timestamp_str:
                timestamp = datetime.strptime(timestamp_str.replace('Z', '+00:00'), '%Y-%m-%dT%H:%M:%S.%f%z')
            else:
                timestamp = datetime.utcnow()

            # Look for content resource
            content_uid = None
            content_resource_elem = change_elem.find('contentResource')
            if content_resource_elem is not None:
                content_uid_elem = content_resource_elem.find('uid')
                if content_uid_elem is not None and content_uid_elem.text:
                    content_uid = content_uid_elem.text

            # Look for mission UID
            mission_uid = None
            mission_uid_elem = change_elem.find('missionUid')
            if mission_uid_elem is not None and mission_uid_elem.text:
                mission_uid = mission_uid_elem.text

            # Create MissionChange record with isFederatedChange=True
            mission_change = MissionChange(
                content_uid=content_uid,
                isFederatedChange=True,  # Mark as federated to prevent loops
                change_type=change_type,
                mission_name=mission.name,
                timestamp=timestamp,
                creator_uid=author_uid,
                server_time=datetime.utcnow(),
                mission_uid=mission_uid
            )

            db.session.add(mission_change)

            logger.info(f"Created federated mission change: {change_type} for mission {mission.name}")

            # Note: Broadcasting to local clients via RabbitMQ would be done here
            # but requires RabbitMQ channel integration which is complex
            # For now, the mission change is persisted to the database

        except Exception as e:
            logger.error(f"Failed to process mission change: {e}", exc_info=True)



class FederationListener:
    """
    Listens for incoming federation connections on a specific port.

    Handles:
    - TLS server socket creation
    - Accepting incoming connections
    - Mutual TLS authentication
    - Creating FederationConnection instances for accepted connections
    """

    def __init__(self, port: int, protocol_version: str, app_config, service):
        """
        Initialize federation listener.

        Args:
            port: Port to listen on
            protocol_version: Federation protocol version ("v1" or "v2")
            app_config: Application configuration dict
            service: Reference to FederationService for connection management
        """
        self.port = port
        self.protocol_version = protocol_version
        self.app_config = app_config
        self.service = service
        self.running = False
        self.listener_socket: Optional[socket.socket] = None
        self.listener_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the federation listener"""
        logger.info(f"Starting Federation Listener on port {self.port} (protocol: {self.protocol_version})")

        try:
            # Create socket
            self.listener_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Bind to address and port
            bind_address = self.app_config.get('OTS_FEDERATION_BIND_ADDRESS', '0.0.0.0')
            self.listener_socket.bind((bind_address, self.port))
            self.listener_socket.listen(5)

            # Set timeout so we can periodically check if we should stop
            self.listener_socket.settimeout(5.0)

            logger.info(f"Federation Listener bound to {bind_address}:{self.port}")

            # Start listening thread
            self.running = True
            self.listener_thread = threading.Thread(
                target=self._listen_loop,
                daemon=True,
                name=f"FederationListener-{self.protocol_version}-{self.port}"
            )
            self.listener_thread.start()

            return True

        except Exception as e:
            logger.error(f"Failed to start federation listener on port {self.port}: {e}", exc_info=True)
            if self.listener_socket:
                try:
                    self.listener_socket.close()
                except:
                    pass
            return False

    def stop(self):
        """Stop the federation listener"""
        logger.info(f"Stopping Federation Listener on port {self.port}")

        self.running = False

        if self.listener_socket:
            try:
                self.listener_socket.close()
            except Exception as e:
                logger.error(f"Error closing listener socket: {e}")

        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=10)

        logger.info(f"Federation Listener stopped on port {self.port}")

    def _listen_loop(self):
        """
        Background thread that accepts incoming federation connections.
        """
        logger.info(f"Federation listener loop started on port {self.port}")

        while self.running:
            try:
                # Accept connection (with timeout)
                try:
                    client_socket, client_address = self.listener_socket.accept()
                except socket.timeout:
                    # Timeout is expected - allows us to check self.running periodically
                    continue
                except OSError as e:
                    # Socket was closed
                    if not self.running:
                        break
                    raise

                logger.info(f"Accepted federation connection from {client_address[0]}:{client_address[1]}")

                # Handle the connection in a separate thread
                handler_thread = threading.Thread(
                    target=self._handle_connection,
                    args=(client_socket, client_address),
                    daemon=True,
                    name=f"FederationHandler-{client_address[0]}"
                )
                handler_thread.start()

            except Exception as e:
                if self.running:
                    logger.error(f"Error in federation listener loop: {e}", exc_info=True)
                    time.sleep(5)

        logger.info(f"Federation listener loop stopped on port {self.port}")

    def _handle_connection(self, client_socket: socket.socket, client_address: tuple):
        """
        Handle an accepted connection by wrapping with TLS and creating FederationConnection.

        Args:
            client_socket: Accepted client socket
            client_address: Tuple of (ip, port) for the client
        """
        wrapped_socket = None
        peer_cert = None
        client_ip = client_address[0]
        client_port = client_address[1]

        try:
            # Wrap with TLS
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

            # Load server certificate and key
            cert_file = self.app_config.get('OTS_FEDERATION_CERT_FILE')
            key_file = self.app_config.get('OTS_FEDERATION_KEY_FILE')

            if not cert_file or not key_file:
                logger.error("Federation server certificate or key file not configured")
                client_socket.close()
                return

            if not os.path.exists(cert_file) or not os.path.exists(key_file):
                logger.error(f"Federation server certificate or key file not found: {cert_file}, {key_file}")
                client_socket.close()
                return

            context.load_cert_chain(certfile=cert_file, keyfile=key_file)

            # Configure mutual TLS (require client certificate)
            context.verify_mode = ssl.CERT_REQUIRED

            # Load CA certificate or truststore for client verification
            ca_file = self.app_config.get('OTS_FEDERATION_CA_FILE')
            truststore_dir = self.app_config.get('OTS_FEDERATION_TRUSTSTORE_DIR')

            if ca_file and os.path.exists(ca_file):
                context.load_verify_locations(cafile=ca_file)
                logger.debug(f"Loaded CA file: {ca_file}")
            elif truststore_dir and os.path.exists(truststore_dir):
                context.load_verify_locations(capath=truststore_dir)
                logger.debug(f"Loaded truststore directory: {truststore_dir}")
            else:
                logger.warning("No CA file or truststore directory configured - using default verification")

            # Wrap socket with TLS
            wrapped_socket = context.wrap_socket(client_socket, server_side=True)

            # Get peer certificate
            peer_cert = wrapped_socket.getpeercert()

            # Log certificate information
            if peer_cert:
                subject = dict(x[0] for x in peer_cert.get('subject', ()))
                issuer = dict(x[0] for x in peer_cert.get('issuer', ()))
                cn = subject.get('commonName', 'Unknown')
                logger.info(f"Client certificate CN: {cn}, Issuer: {issuer.get('commonName', 'Unknown')}")
            else:
                logger.warning(f"No client certificate received from {client_ip}")

            # Create or update FederationServer record
            federation_server = self._create_or_update_server(
                client_ip, client_port, peer_cert
            )

            if not federation_server:
                logger.error(f"Failed to create federation server record for {client_ip}")
                wrapped_socket.close()
                return

            # Create FederationConnection instance
            connection = FederationConnection(
                federation_server=federation_server,
                app_config=self.app_config,
                is_inbound=True,
                wrapped_socket=wrapped_socket
            )

            # Start the connection
            if connection.connect():
                # Store in service's inbound connections
                self.service.inbound_connections[federation_server.id] = connection
                logger.info(f"Inbound federation connection established with {federation_server.name}")
            else:
                logger.error(f"Failed to initialize inbound connection from {client_ip}")
                wrapped_socket.close()

        except ssl.SSLError as e:
            logger.error(f"SSL error during federation connection from {client_ip}: {e}")
            if wrapped_socket:
                try:
                    wrapped_socket.close()
                except:
                    pass
            elif client_socket:
                try:
                    client_socket.close()
                except:
                    pass

        except Exception as e:
            logger.error(f"Error handling federation connection from {client_ip}: {e}", exc_info=True)
            if wrapped_socket:
                try:
                    wrapped_socket.close()
                except:
                    pass
            elif client_socket:
                try:
                    client_socket.close()
                except:
                    pass

    def _create_or_update_server(self, client_ip: str, client_port: int,
                                  peer_cert: Optional[dict]) -> Optional[FederationServer]:
        """
        Create or update FederationServer record for an inbound connection.

        Args:
            client_ip: Client IP address
            client_port: Client port number
            peer_cert: Client's SSL certificate (parsed)

        Returns:
            FederationServer object or None if failed
        """
        try:
            with db.session.begin():
                # Extract common name from certificate
                server_name = client_ip
                node_id = None

                if peer_cert:
                    subject = dict(x[0] for x in peer_cert.get('subject', ()))
                    cn = subject.get('commonName')
                    if cn:
                        server_name = cn
                        node_id = cn

                # Check if server already exists (by address)
                server = db.session.query(FederationServer).filter_by(
                    address=client_ip,
                    connection_type=FederationServer.INBOUND
                ).first()

                if server:
                    # Update existing server
                    logger.debug(f"Updating existing inbound federation server: {server.name}")
                    server.last_connected = datetime.utcnow()
                    server.status = FederationServer.STATUS_CONNECTED
                    server.port = client_port
                    if node_id:
                        server.node_id = node_id
                else:
                    # Create new server
                    logger.info(f"Creating new inbound federation server: {server_name}")
                    server = FederationServer(
                        name=f"inbound-{server_name}",
                        description=f"Inbound federation connection from {client_ip}",
                        address=client_ip,
                        port=client_port,
                        connection_type=FederationServer.INBOUND,
                        protocol_version=self.protocol_version,
                        use_tls=True,
                        verify_ssl=True,
                        enabled=True,
                        status=FederationServer.STATUS_CONNECTED,
                        sync_missions=True,
                        sync_cot=True,
                        node_id=node_id
                    )
                    db.session.add(server)
                    db.session.flush()  # Get the ID

                return server

        except Exception as e:
            logger.error(f"Error creating/updating federation server for {client_ip}: {e}", exc_info=True)
            return None


class FederationService:
    """
    Main federation service that manages all federation connections.

    This service:
    - Maintains connections to all enabled outbound federation servers
    - Monitors connection health
    - Handles reconnection logic
    - Manages inbound federation server listeners
    """

    def __init__(self, app_config):
        self.app_config = app_config
        self.connections: dict[int, FederationConnection] = {}
        self.inbound_connections: dict[int, FederationConnection] = {}
        self.listeners: dict[str, FederationListener] = {}
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the federation service"""
        if not self.app_config.get('OTS_ENABLE_FEDERATION', False):
            logger.info("Federation is disabled")
            return

        logger.info("Starting Federation Service")
        self.running = True

        # Start inbound listeners for v1 and v2 protocols
        v1_port = self.app_config.get('OTS_FEDERATION_V1_PORT', 9000)
        v2_port = self.app_config.get('OTS_FEDERATION_V2_PORT', 9001)

        # Start v1 listener
        v1_listener = FederationListener(v1_port, "v1", self.app_config, self)
        if v1_listener.start():
            self.listeners['v1'] = v1_listener
            logger.info(f"Federation v1 listener started on port {v1_port}")
        else:
            logger.error(f"Failed to start federation v1 listener on port {v1_port}")

        # Start v2 listener
        v2_listener = FederationListener(v2_port, "v2", self.app_config, self)
        if v2_listener.start():
            self.listeners['v2'] = v2_listener
            logger.info(f"Federation v2 listener started on port {v2_port}")
        else:
            logger.error(f"Failed to start federation v2 listener on port {v2_port}")

        # Start connection monitor thread
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

        logger.info("Federation Service started")

    def stop(self):
        """Stop the federation service"""
        logger.info("Stopping Federation Service")
        self.running = False

        # Stop all listeners
        for listener_name, listener in list(self.listeners.items()):
            logger.info(f"Stopping federation listener: {listener_name}")
            listener.stop()

        self.listeners.clear()

        # Disconnect all outbound connections
        for connection in list(self.connections.values()):
            connection.disconnect()

        self.connections.clear()

        # Disconnect all inbound connections
        for connection in list(self.inbound_connections.values()):
            connection.disconnect()

        self.inbound_connections.clear()

        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=10)

        logger.info("Federation Service stopped")

    def _monitor_loop(self):
        """
        Background thread that monitors federation connections and handles reconnection.
        """
        logger.info("Starting federation monitor loop")

        while self.running:
            try:
                # Query for enabled outbound federation servers
                with db.session.begin():
                    servers = db.session.query(FederationServer).filter_by(
                        enabled=True,
                        connection_type=FederationServer.OUTBOUND
                    ).all()

                    for server in servers:
                        # Check if we have an active connection
                        if server.id not in self.connections or not self.connections[server.id].connected:
                            # Try to establish connection
                            logger.info(f"Attempting to connect to federation server: {server.name}")
                            connection = FederationConnection(server, self.app_config)

                            if connection.connect():
                                self.connections[server.id] = connection
                            else:
                                # Connection failed, will retry on next loop
                                logger.warning(f"Failed to connect to {server.name}, will retry")

                # Remove disconnected outbound connections
                for server_id in list(self.connections.keys()):
                    if not self.connections[server_id].connected:
                        logger.info(f"Removing disconnected outbound connection for server ID {server_id}")
                        del self.connections[server_id]

                # Remove disconnected inbound connections
                for server_id in list(self.inbound_connections.keys()):
                    if not self.inbound_connections[server_id].connected:
                        logger.info(f"Removing disconnected inbound connection for server ID {server_id}")
                        # Update database status
                        try:
                            with db.session.begin():
                                server = db.session.query(FederationServer).get(server_id)
                                if server:
                                    server.status = FederationServer.STATUS_DISCONNECTED
                        except Exception as db_error:
                            logger.error(f"Failed to update inbound server status: {db_error}")
                        del self.inbound_connections[server_id]

                # Sleep before next check
                time.sleep(self.app_config.get('OTS_FEDERATION_RETRY_INTERVAL', 60))

            except Exception as e:
                logger.error(f"Error in federation monitor loop: {e}", exc_info=True)
                time.sleep(30)

        logger.info("Federation monitor loop stopped")

    def queue_mission_change(self, mission_change_id: int):
        """
        Queue a mission change to be sent to all federated servers.

        Args:
            mission_change_id: ID of the mission change to send
        """
        try:
            with db.session.begin():
                # Get all enabled federation servers that sync missions
                servers = db.session.query(FederationServer).filter_by(
                    enabled=True,
                    sync_missions=True
                ).all()

                for server in servers:
                    # Check if this mission change should be sent to this server
                    # (based on mission_filter if configured)

                    # Create outbound record
                    outbound = FederationOutbound(
                        federation_server_id=server.id,
                        mission_change_id=mission_change_id,
                        sent=False
                    )
                    db.session.add(outbound)

                logger.debug(f"Queued mission change {mission_change_id} for {len(servers)} federation servers")

        except Exception as e:
            logger.error(f"Error queuing mission change for federation: {e}", exc_info=True)
