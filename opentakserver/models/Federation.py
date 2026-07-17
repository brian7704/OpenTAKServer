from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime


@dataclass
class Federation(db.Model):
    """A federate: another TAK server we exchange data with.

    Outbound federates are dialed by the federation server; inbound federates
    are auto-registered when a server whose CA is in the federation truststore
    connects. ``inbound_groups``/``outbound_groups`` gate the flow of data in
    each direction - a federate with empty group lists exchanges nothing,
    matching TAK Server's default posture.
    """

    __tablename__ = "federation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=True)
    port: Mapped[int] = mapped_column(Integer, default=9000, nullable=True)
    protocol_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    outbound: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reconnect_interval: Mapped[int] = mapped_column(Integer, default=30, nullable=True)
    cert_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=True)
    cert_common_name: Mapped[str] = mapped_column(String(255), nullable=True)
    inbound_groups: Mapped[JSON] = mapped_column(JSON, default=[], nullable=True)
    outbound_groups: Mapped[JSON] = mapped_column(JSON, default=[], nullable=True)
    last_connected: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_disconnected: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(255), nullable=True)

    def serialize(self):
        return {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "port": self.port,
            "protocol_version": self.protocol_version,
            "outbound": self.outbound,
            "enabled": self.enabled,
            "reconnect_interval": self.reconnect_interval,
            "cert_fingerprint": self.cert_fingerprint,
            "cert_common_name": self.cert_common_name,
            "inbound_groups": self.inbound_groups,
            "outbound_groups": self.outbound_groups,
            "last_connected": self.last_connected,
            "last_disconnected": self.last_disconnected,
            "last_error": self.last_error,
        }

    def to_json(self):
        json = self.serialize()
        json["last_connected"] = (
            iso8601_string_from_datetime(self.last_connected) if self.last_connected else None
        )
        json["last_disconnected"] = (
            iso8601_string_from_datetime(self.last_disconnected)
            if self.last_disconnected
            else None
        )
        return json
