from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class Team(db.Model):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    chatroom_id: Mapped[str] = mapped_column(String(255), ForeignKey("chatrooms.id"), nullable=True)
    euds = relationship("EUD", back_populates="team")
    chatroom = relationship("Chatroom", back_populates="team")
    mission_invitations = relationship("MissionInvitation", back_populates="team")

    colors = {'Cyan': '#00FFFF', 'White': '#000000', 'Yellow': '#FFFF00', 'Orange': '#FFA500', 'Magenta': '#FF00FF',
              'Red': '#FF0000', 'Maroon': '#800000', 'Purple': '#800080', 'Dark Blue': '#00008B', 'Blue': '#0000FF',
              'Teal': '#008080', 'Green': '#00FF00', 'Dark Green': '#228B22', 'Brown': '#964B00'}

    def get_team_color(self):
        return self.colors[self.name]

    def serialize(self):
        return {
            'name': self.name,
        }

    def to_json(self):
        return {
            'name': self.name,
            'chatroom': self.chatroom.to_json() if self.chatroom else None,
            'euds': [eud.to_json() for eud in self.euds] if self.euds else None,
            'color': self.colors[self.name]
        }
