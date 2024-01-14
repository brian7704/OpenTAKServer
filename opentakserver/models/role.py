from dataclasses import dataclass

from flask_security.models import fsqla_v3 as fsqla
from opentakserver.extensions import db, logger


@dataclass
class Role(db.Model, fsqla.FsRoleMixin):

    def serialize(self):
        return {
            'name': self.name,
            'description': self.description,
            'permissions': self.permissions,
            'update_timestamp': self.update_datetime,
        }