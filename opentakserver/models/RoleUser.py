from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class RoleUser(db.Model):
    __tablename__ = "roles_users"

    user_id: Mapped[Integer] = mapped_column(Integer, ForeignKey("user.id"), primary_key=True)
    role_id: Mapped[Integer] = mapped_column(Integer, ForeignKey("role.id"), primary_key=True)
    user_info = relationship("User", cascade="all, delete", viewonly=True)
    role_info = relationship("Role", cascade="all, delete", viewonly=True)

    def serialize(self):
        return {
            'user_id': self.user_id,
            'role_id': self.role_id
        }
