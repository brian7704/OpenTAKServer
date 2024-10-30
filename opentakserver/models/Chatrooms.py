from opentakserver.extensions import db
from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Chatroom(db.Model):
    __tablename__ = 'chatrooms'

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    group_owner: Mapped[str] = mapped_column(String(255), nullable=True)
    parent: Mapped[str] = mapped_column(String(255), nullable=True)
    geochats = relationship("GeoChat", cascade="all, delete-orphan", back_populates="chatroom")
    chatroom_uid = relationship("ChatroomsUids", cascade="all, delete-orphan", back_populates="chatroom")
    team = relationship("Team", back_populates="chatroom")

    def serialize(self):
        return {
            'name': self.name,
            'group_owner': self.group_owner,
            'parent': self.parent,
        }

    def to_json(self):
        return {
            'name': self.name,
            'group_owner': self.group_owner,
            'parent': self.parent,
            'geochats': [chat.to_json() for chat in self.geochats] if self.geochats else None
        }
