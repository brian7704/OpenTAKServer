from extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship


class UsersEuds(db.Model):
    __tablename__ = 'users_euds'

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), primary_key=True)
    eud_uid: Mapped[str] = mapped_column(Integer, ForeignKey("eud.uid"), primary_key=True)
    user = relationship("User", back_populates="euds")
    eud = relationship("EUD", back_populates="user")
