import enum

from sqlalchemy import ForeignKey, Integer, String, Boolean, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db


class AuthTokenTypeEnum(enum.Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class FederationConnections(db.model):
    __tablename__ = "federation_connections"

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean)
    # Setting protocol_version to a string in case future versions use semver or something else non-numeric
    protocol_version: Mapped[str] = mapped_column(String(255), default="2")
    reconnect_interval: Mapped[int] = mapped_column(Integer, default=30)
    unlimited_retries: Mapped[bool] = mapped_column(Boolean)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    federate: Mapped[str] = mapped_column(String(255), nullable=True)
    fallback_connection: Mapped[int] = mapped_column(
        Integer, ForeignKey("federation_connections.id"), nullable=True
    )
    use_token_auth: Mapped[bool] = mapped_column(Boolean)
    auth_token_type: Mapped[enum] = mapped_column(Enum(AuthTokenTypeEnum), nullable=True)
    auth_token: Mapped[str] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str] = mapped_column(String(1024), nullable=True)
