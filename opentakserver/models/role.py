from dataclasses import dataclass

from flask_security.models import fsqla_v3 as fsqla
from extensions import db


@dataclass
class Role(db.Model, fsqla.FsRoleMixin):

    def serialize(self):
        return {
            'role': {
                'name': self.name,
                'description': self.description,
                'permissions': self.permissions,
                'update_timestamp': self.update_datetime,
            }
        }