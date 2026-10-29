from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db


class FederateGroups(db.Model):
    __tablename__ = "federate_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    federation_id: Mapped[int] = mapped_column(Integer, ForeignKey("federation_connections.id"))
    group_name: Mapped[str] = mapped_column(String(255))

    federation_connection = relationship(
        "FederationConnection", cascade="all, delete", viewonly=True
    )

    def serialize(self):
        return {"federation_id": self.federation_id, "group_name": self.group_name}

    def to_json(self):
        return {"federation_id": self.federation_id, "group_name": self.group_name, "id": self.id}
