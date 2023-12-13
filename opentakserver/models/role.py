from flask_security.models import fsqla_v3 as fsqla
from extensions import db


class Role(db.Model, fsqla.FsRoleMixin):
    pass

