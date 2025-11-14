import datetime
from dataclasses import dataclass
from opentakserver.extensions import db
from sqlalchemy import Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column


@dataclass
class FederationServer(db.Model):
    """
    Represents a federated TAK server connection.

    Federation allows multiple TAK servers to synchronize mission data and CoT messages.
    Supports both Federation v1 (port 9000) and v2 (port 9001) protocols.
    """
    __tablename__ = "federation_servers"

    # Connection types
    OUTBOUND = "outbound"  # This server initiates connection to remote
    INBOUND = "inbound"    # Remote server connects to this server

    # Federation protocol versions
    FEDERATION_V1 = "v1"  # Legacy federation protocol (port 9000)
    FEDERATION_V2 = "v2"  # Current federation protocol (port 9001)

    # Transport protocols
    TRANSPORT_TCP = "tcp"        # TCP transport (default)
    TRANSPORT_UDP = "udp"        # UDP transport
    TRANSPORT_MULTICAST = "multicast"  # Multicast transport

    # Connection status
    STATUS_CONNECTED = "connected"
    STATUS_DISCONNECTED = "disconnected"
    STATUS_ERROR = "error"
    STATUS_DISABLED = "disabled"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Server identification
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    node_id: Mapped[str] = mapped_column(String(255), nullable=True)  # Remote server's node ID

    # Connection details
    address: Mapped[str] = mapped_column(String(255), nullable=False)  # IP or hostname
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    connection_type: Mapped[str] = mapped_column(String(50), nullable=False, default=OUTBOUND)
    protocol_version: Mapped[str] = mapped_column(String(10), nullable=False, default=FEDERATION_V2)
    transport_protocol: Mapped[str] = mapped_column(String(20), nullable=False, default=TRANSPORT_TCP)

    # TLS/SSL Configuration
    use_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ca_certificate: Mapped[str] = mapped_column(Text, nullable=True)  # Remote server's CA certificate
    client_certificate: Mapped[str] = mapped_column(Text, nullable=True)  # Our client cert for outbound
    client_key: Mapped[str] = mapped_column(Text, nullable=True)  # Our client key for outbound
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Status and monitoring
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=STATUS_DISCONNECTED, nullable=False)
    last_connected: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)

    # Mission synchronization settings
    sync_missions: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sync_cot: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Filtering
    mission_filter: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array of mission names to sync

    # Metadata
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow,
                                                          onupdate=datetime.datetime.utcnow, nullable=False)

    def to_json(self):
        """Serialize federation server to JSON (excluding sensitive data)"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "node_id": self.node_id,
            "address": self.address,
            "port": self.port,
            "connection_type": self.connection_type,
            "protocol_version": self.protocol_version,
            "transport_protocol": self.transport_protocol,
            "use_tls": self.use_tls,
            "verify_ssl": self.verify_ssl,
            "enabled": self.enabled,
            "status": self.status,
            "last_connected": self.last_connected.isoformat() if self.last_connected else None,
            "last_error": self.last_error,
            "sync_missions": self.sync_missions,
            "sync_cot": self.sync_cot,
            "mission_filter": self.mission_filter,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<FederationServer {self.name} ({self.address}:{self.port})>"
