import datetime
from dataclasses import dataclass
from opentakserver.extensions import db
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class FederationOutbound(db.Model):
    """
    Tracks mission changes that have been sent to federated servers.

    This enables:
    - Avoiding duplicate sends
    - Mission Federation Disruption Tolerance
    - Tracking synchronization status across federated servers
    """
    __tablename__ = "federation_outbound"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Foreign keys
    federation_server_id: Mapped[int] = mapped_column(Integer, ForeignKey("federation_servers.id", ondelete="CASCADE"),
                                                       nullable=False)
    mission_change_id: Mapped[int] = mapped_column(Integer, ForeignKey("mission_changes.id", ondelete="CASCADE"),
                                                    nullable=False)

    # Status tracking
    sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sent_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    acknowledged_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    # Retry tracking for disruption tolerance
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_retry_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(1000), nullable=True)

    # Relationships
    federation_server = relationship("FederationServer", backref="outbound_changes")
    mission_change = relationship("MissionChange", backref="federation_outbound")

    # Metadata
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    def to_json(self):
        """Serialize to JSON"""
        return {
            "id": self.id,
            "federation_server_id": self.federation_server_id,
            "mission_change_id": self.mission_change_id,
            "sent": self.sent,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "retry_count": self.retry_count,
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<FederationOutbound server={self.federation_server_id} change={self.mission_change_id} sent={self.sent}>"
