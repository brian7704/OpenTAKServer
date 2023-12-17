from extensions import db
from sqlalchemy import String
from flask_security.models import fsqla_v3 as fsqla
from sqlalchemy.orm import relationship


class User(db.Model, fsqla.FsUserMixin):
    email = db.Column(String, nullable=True)
    video_streams = relationship("VideoStream", back_populates="user")
    euds = relationship("UsersEuds", back_populates="user")
