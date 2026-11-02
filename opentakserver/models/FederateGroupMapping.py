from sqlalchemy import Integer, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db
from opentakserver.models.Group import Group


class FederateGroupMapping(db.Model):
    __tablename__ = "federate_group_mapping"

    federate_group_id: Mapped[Integer] = mapped_column(
        Integer, ForeignKey("federate_groups.id"), primary_key=True
    )
    group_id: Mapped[Integer] = mapped_column(Integer, ForeignKey("groups.id"), primary_key=True)
    federation_id: Mapped[int] = mapped_column(Integer, ForeignKey("federates.id"))

    group = relationship("Group", cascade="all, delete", viewonly=True)
    federate_group = relationship("FederateGroups", cascade="all, delete", viewonly=True)

    def serialize(self):
        return {
            "federate_group_id": self.federate_group_id,
            "group_id": self.group_id,
            "federation_id": self.federation_id,
        }

    def to_json(self):
        return {
            "federate_group_id": self.federate_group_id,
            "group_id": self.group_id,
            "federation_id": self.federation_id,
            "group": self.group.to_json(),
            "federate_group": self.federate_group.to_json(),
        }
