from extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship


class ChatroomsUids(db.Model):
    __tablename__ = 'chatrooms_uids'

    chatroom_id: Mapped[str] = mapped_column(String, ForeignKey("chatrooms.id"), primary_key=True)
    uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"), primary_key=True)
    chatroom = relationship("Chatroom", back_populates="chatroom_uid")
    eud = relationship("EUD", back_populates="chatroom_uid")
