from extensions import db
from sqlalchemy import String
from flask_security.models import fsqla_v3 as fsqla


class User(db.Model, fsqla.FsUserMixin):
    email = db.Column(String, nullable=True)
    pass
