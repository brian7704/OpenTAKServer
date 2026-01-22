import datetime
import enum
from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


class InvitationTypeEnum(str, enum.Enum):
    clientUid = "clientUid"
    callsign = "callsign"
    userName = "userName"
    group = "group"
    team = "team"


@dataclass
class MissionInvitation(db.Model):
    __tablename__ = "mission_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_name: Mapped[str] = mapped_column(String(255), ForeignKey('missions.name'))
    client_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"), nullable=True)
    callsign: Mapped[str] = mapped_column(String(255), ForeignKey("euds.callsign", ondelete="CASCADE"), nullable=True)
    username: Mapped[str] = mapped_column(String(255), ForeignKey("user.username"), nullable=True)
    group_name: Mapped[str] = mapped_column(String(255), nullable=True)
    team_name: Mapped[str] = mapped_column(String(255), ForeignKey("teams.name"), nullable=True)
    creator_uid: Mapped[str] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(255), nullable=True)
    type: Mapped[str] = mapped_column(String(255), nullable=True, default="callsign")

    eud_uid = relationship("EUD", foreign_keys=[client_uid], uselist=False)
    eud_callsign = relationship("EUD", foreign_keys=[callsign], uselist=False)
    user = relationship("User", back_populates="mission_invitations", uselist=False)
    team = relationship("Team", back_populates="mission_invitations", uselist=False)
    mission = relationship("Mission", back_populates="invitations", uselist=False)

    def serialize(self):
        return {
            'mission_name': self.mission_name,
            'client_uid': self.client_uid,
            'callsign': self.callsign,
            'username': self.username,
            'group_name': self.group,
            'team_name': self.team_name,
            'creator_uid': self.creator_uid,
            'role': self.role,
            'type': self.type
        }

    def to_json(self):
        return self.serialize()
