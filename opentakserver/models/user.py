from dataclasses import dataclass

from opentakserver.extensions import db
from opentakserver.models.Group import Group
# Leave this import here
from opentakserver.models.Token import Token
from opentakserver.models.WebAuthn import WebAuthn
from sqlalchemy import String
from flask_security.models import fsqla_v3 as fsqla
from sqlalchemy.orm import relationship


@dataclass
class User(db.Model, fsqla.FsUserMixin):
    email = db.Column(String(255), nullable=True)
    video_streams = relationship("VideoStream", back_populates="user")
    euds = relationship("EUD", back_populates="user")
    data_packages = relationship("DataPackage", back_populates="user")
    certificate = relationship("Certificate", back_populates="user")
    mission_invitations = relationship("MissionInvitation", back_populates="user")
    tokens = relationship("Token", back_populates="user")
    groups = relationship("Group", secondary="groups_users", viewonly=True, back_populates="users", cascade="all, delete")
    group_memberships = relationship("GroupUser", back_populates="user", cascade="all, delete")

    def serialize(self):
        return {
            'id': self.id,
            'username': self.username,
            'active': self.active,
            'last_login_at': self.last_login_at,
            'last_login_ip': self.last_login_ip,
            'current_login_at': self.current_login_at,
            'current_login_ip': self.current_login_ip,
            'email': self.email,
            'login_count': self.login_count,
            'euds': [eud.serialize() for eud in self.euds],
            'video_streams': [v.serialize() for v in self.video_streams],
            'roles': [role.serialize() for role in self.roles],
            'groups': [group.serialize() for group in self.groups],
            'group_memberships': [membership.to_json() for membership in self.group_memberships]
        }

    def to_json(self):
        response = self.serialize()
        response['token'] = self.get_auth_token()
        return response
