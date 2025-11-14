from dataclasses import dataclass

from flask_security.models import fsqla_v3 as fsqla
from sqlalchemy.orm import relationship

from opentakserver.extensions import db, logger


@dataclass
class Role(db.Model, fsqla.FsRoleMixin):
    users = relationship("User", secondary="roles_users", viewonly=True, back_populates="roles", cascade="all, delete")

    def serialize(self):
        return {
            'name': self.name,
            'description': self.description,
            'permissions': self.permissions,
            'update_timestamp': self.update_datetime,
        }

    def __eq__(self, other):
        return self.name == other or self.name == getattr(other, "name", None)
