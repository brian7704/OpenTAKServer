from extensions import db
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Chatroom(db.Model):
    __tablename__ = 'chatrooms'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    group_owner: Mapped[str] = mapped_column(String, nullable=True)
    parent: Mapped[str] = mapped_column(String, nullable=True)
    geochats = relationship("GeoChat", back_populates="chatroom")
    chatroom_uid = relationship("ChatroomsUids", back_populates="chatroom")
