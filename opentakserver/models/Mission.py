import datetime
from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column


@dataclass
class Mission(db.Model):
    __tablename__ = "missions"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    description: Mapped[str] = mapped_column(String, nullable=True)
    chatRoom: Mapped[str] = mapped_column(String, nullable=True)
    baseLayer: Mapped[str] = mapped_column(String, nullable=True)
    bbox: Mapped[str] = mapped_column(String, nullable=True)
    path: Mapped[str] = mapped_column(String, nullable=True)
    classification: Mapped[str] = mapped_column(String, nullable=True)
    tool: Mapped[str] = mapped_column(String, nullable=True)
    group: Mapped[str] = mapped_column(String, nullable=True)
    defaultRole: Mapped[str] = mapped_column(String, nullable=True)
    permissions: Mapped[str] = mapped_column(String, nullable=True)
    keywords: Mapped[str] = mapped_column(String, nullable=True)
    creatorUid: Mapped[str] = mapped_column(String, nullable=True)
    creationTime: Mapped[int] = mapped_column(Integer, nullable=True)
    externalData: Mapped[str] = mapped_column(String, nullable=True)
    feeds: Mapped[str] = mapped_column(String, nullable=True)
    mapLayers: Mapped[str] = mapped_column(String, nullable=True)
    inviteOnly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expiration: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    guid: Mapped[str] = mapped_column(String, nullable=True)
    uids: Mapped[str] = mapped_column(String, nullable=True)
    contents: Mapped[str] = mapped_column(String, nullable=True)
    passwordProtected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def serialize(self):
        return {
            'name': self.name,
            'description': self.description,
            'chatroom': self.chatRoom,
            'base_layer': self.baseLayer,
            'bbox': self.bbox,
            'path': self.path,
            'classification': self.classification,
            'tool': self.tool,
            'group': self.group,
            'default_role': self.defaultRole,
            'keywords': self.keywords,
            'creatorUid': self.creatorUid,
            'creationTime': self.creationTime,
            'externalData': self.externalData,
            'feeds': self.feeds,
            'mapLayers': self.mapLayers,
            'inviteOnly': self.inviteOnly,
            'expiration': self.expiration,
            'guid': self.guid,
            'uids': self.uids,
            'contents': self.contents,
            'passwordProtected': self.passwordProtected
        }

    def to_json(self):
        return self.serialize()
