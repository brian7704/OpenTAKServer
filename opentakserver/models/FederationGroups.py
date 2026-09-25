import enum
import uuid

from sqlalchemy import ForeignKey, Integer, String, Boolean, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db
from opentakserver.forms.FederationConnectionForm import FederationConnectionForm
from opentakserver.models.Group import Group


class FederationGroups(db.Model):
    __tablename__ = "federation_groups"

    federation_id = db.Column(db.Integer, ForeignKey("federation_connections.id"), primary_key=True)
    group_id = db.Column(db.Integer, ForeignKey("groups.id"), primary_key=True)
    direction: Mapped[String] = mapped_column(String(255), primary_key=True)
    federation_connection = relationship("FederationConnection", cascade="all, delete", viewonly=True)
    group = relationship("Group", cascade="all, delete", viewonly=True)

    def serialize(self):
        return {
            "federation_id": self.federation_id,
            "group_id": self.group_id,
        }

    def to_json(self):
        return {
            "federation_id": self.federation_id,
            "group_id": self.group_id,
            "direction": self.direction,
            "group": self.group.to_json(),
            "federation_connection": self.federation_connection.to_json()
        }
