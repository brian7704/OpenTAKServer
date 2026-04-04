import enum
import uuid

from sqlalchemy import ForeignKey, Integer, String, Boolean, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db
from opentakserver.forms.FederationConnectionForm import FederationConnectionForm


class AuthTokenTypeEnum(enum.Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class FederationConnection(db.Model):
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
    federate_id: Mapped[int] = mapped_column(Integer, ForeignKey("federates.id"), nullable=True)
    fallback_connection: Mapped[int] = mapped_column(
        Integer, ForeignKey("federation_connections.id"), nullable=True
    )
    use_token_auth: Mapped[bool] = mapped_column(Boolean)
    auth_token_type: Mapped[enum] = mapped_column(Enum(AuthTokenTypeEnum), nullable=True)
    auth_token: Mapped[int] = mapped_column(
        Integer, ForeignKey("federate_tokens.id"), nullable=True
    )
    last_error: Mapped[str] = mapped_column(String(1024), nullable=True)
    description: Mapped[str] = mapped_column(String(1024), nullable=True)
    uid: Mapped[str] = mapped_column(String(255), nullable=True)
    federate = relationship("Federate", back_populates="federation_connection", uselist=False)

    def from_wtforms(self, form: FederationConnectionForm):
        self.display_name = form.display_name.data
        self.address = form.address.data
        self.port = form.port.data
        self.enabled = form.enabled.data
        self.protocol_version = form.protocol_version.data
        self.reconnect_interval = form.reconnect_interval.data
        self.unlimited_retries = form.unlimited_retries.data
        self.max_retries = form.max_retries.data
        self.federate_id = form.federate_id.data
        self.fallback_connection = form.fallback_connection.data
        self.use_token_auth = form.use_token_auth.data
        self.auth_token_type = form.auth_token_type.data
        self.auth_token = form.auth_token.data
        self.last_error = form.last_error.data
        self.description = form.description.data
        self.uid = str(uuid.uuid4())
