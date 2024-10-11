import datetime
from dataclasses import dataclass

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.constants import MissionRoleConstants
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class MissionRole(db.Model):
    __tablename__ = "mission_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clientUid: Mapped[str] = mapped_column(String)
    username: Mapped[str] = mapped_column(String)
    createTime: Mapped[datetime] = mapped_column(DateTime)
    role_type: Mapped[str] = mapped_column(String)
    mission_name: Mapped[str] = mapped_column(String, ForeignKey("missions.name"))
    mission = relationship("Mission", back_populates="roles", uselist=False)

    def serialize(self):
        return {
            'clientUid': self.clientUid,
            'username': self.username,
            'createTime': self.createTime,
            'role_type': self.role_type
        }

    def to_json(self):
        json = {
            'clientUid': self.clientUid,
            'username': self.username,
            'createTime': iso8601_string_from_datetime(self.createTime),
            'role': {
                'type': self.role_type,
                'permissions': []
            }
        }

        if self.role_type == MissionRoleConstants.MISSION_OWNER:
            json['role'] = MissionRoleConstants.OWNER_ROLE

        elif self.role_type == MissionRoleConstants.MISSION_SUBSCRIBER:
            json['role'] = MissionRoleConstants.SUBSCRIBER_ROLE

        else:
            json['role'] = MissionRoleConstants.READ_ONLY_ROLE

        return json
