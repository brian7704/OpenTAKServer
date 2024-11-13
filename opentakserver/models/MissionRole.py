import datetime
from dataclasses import dataclass

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class MissionRole(db.Model):
    __tablename__ = "mission_roles"

    MISSION_MANAGE_FEEDS = "MISSION_MANAGE_FEEDS"
    MISSION_SET_PASSWORD = "MISSION_SET_PASSWORD"
    MISSION_WRITE = "MISSION_WRITE"
    MISSION_MANAGE_LAYERS = "MISSION_MANAGE_LAYERS"
    MISSION_UPDATE_GROUPS = "MISSION_UPDATE_GROUPS"
    MISSION_DELETE = "MISSION_DELETE"
    MISSION_SET_ROLE = "MISSION_SET_ROLE"
    MISSION_READ = "MISSION_READ"
    MISSION_OWNER = "MISSION_OWNER"
    MISSION_SUBSCRIBER = "MISSION_SUBSCRIBER"
    MISSION_READ_ONLY = "MISSION_READ_ONLY"

    OWNER_ROLE = {'type': MISSION_OWNER, 'permissions': []}
    OWNER_ROLE['permissions'].append(MISSION_MANAGE_FEEDS)
    OWNER_ROLE['permissions'].append(MISSION_SET_PASSWORD)
    OWNER_ROLE['permissions'].append(MISSION_WRITE)
    OWNER_ROLE['permissions'].append(MISSION_MANAGE_LAYERS)
    OWNER_ROLE['permissions'].append(MISSION_UPDATE_GROUPS)
    OWNER_ROLE['permissions'].append(MISSION_DELETE)
    OWNER_ROLE['permissions'].append(MISSION_SET_ROLE)
    OWNER_ROLE['permissions'].append(MISSION_READ)

    SUBSCRIBER_ROLE = {'type': MISSION_SUBSCRIBER, 'permissions': []}
    SUBSCRIBER_ROLE['permissions'].append(MISSION_READ)
    SUBSCRIBER_ROLE['permissions'].append(MISSION_WRITE)

    READ_ONLY_ROLE = {'type': MISSION_READ_ONLY, 'permissions': []}
    READ_ONLY_ROLE['permissions'].append(MISSION_READ)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clientUid: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    createTime: Mapped[datetime] = mapped_column(DateTime)
    role_type: Mapped[str] = mapped_column(String(255))
    mission_name: Mapped[str] = mapped_column(String(255), ForeignKey("missions.name"))
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

        if self.role_type == self.MISSION_OWNER:
            json['role'] = self.OWNER_ROLE

        elif self.role_type == self.MISSION_SUBSCRIBER:
            json['role'] = self.SUBSCRIBER_ROLE

        else:
            json['role'] = self.READ_ONLY_ROLE

        return json
