import datetime
from dataclasses import dataclass
from flask import request, current_app as app

from opentakserver.functions import iso8601_string_from_datetime
from opentakserver.extensions import db, logger
from sqlalchemy import Integer, String, Boolean, JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.models.MissionRole import MissionRole


@dataclass
class Mission(db.Model):
    __tablename__ = "missions"

    INVITE = "INVITE"
    DELETE = "DELETE"
    CREATE = "CREATE"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), nullable=True)
    chat_room: Mapped[str] = mapped_column(String(255), nullable=True)
    base_layer: Mapped[str] = mapped_column(String(255), nullable=True)
    bbox: Mapped[str] = mapped_column(String(255), nullable=True)
    path: Mapped[str] = mapped_column(String(255), nullable=True)
    classification: Mapped[str] = mapped_column(String(255), nullable=True)
    tool: Mapped[str] = mapped_column(String(255), nullable=True)
    group: Mapped[str] = mapped_column(String(255), nullable=True)
    default_role: Mapped[str] = mapped_column(String(255), nullable=True)
    keywords: Mapped[JSON] = mapped_column(JSON, nullable=True)
    creator_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"), nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    external_data: Mapped[JSON] = mapped_column(JSON, nullable=True)
    feeds: Mapped[JSON] = mapped_column(JSON, nullable=True)
    map_layers: Mapped[JSON] = mapped_column(JSON, nullable=True)
    invite_only: Mapped[bool] = mapped_column(Boolean, nullable=True)
    expiration: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    guid: Mapped[str] = mapped_column(String(255), nullable=True)
    password_protected: Mapped[bool] = mapped_column(Boolean, nullable=True)
    password: Mapped[str] = mapped_column(String(255), nullable=True)
    invitations = relationship("MissionInvitation", cascade="all, delete-orphan",  back_populates="mission")
    roles = relationship("MissionRole", cascade="all, delete-orphan",  back_populates="mission")
    mission_changes = relationship("MissionChange", cascade="all, delete-orphan",  back_populates="mission", uselist=True)
    contents = relationship("MissionContent", cascade="all",  secondary="mission_content_mission", back_populates="mission", uselist=True)
    cots = relationship("CoT", back_populates="mission", uselist=True)
    uids = relationship("MissionUID", cascade="all, delete-orphan", back_populates="mission")
    mission_logs = relationship("MissionLogEntry", cascade="all, delete-orphan", back_populates="mission")
    owner = relationship("EUD", back_populates="owned_missions")

    def serialize(self):
        return {
            'description': self.description,
            'chat_room': self.chat_room,
            'base_layer': self.base_layer,
            'bbox': self.bbox,
            'path': self.path,
            'classification': self.classification,
            'tool': self.tool,
            'group': self.group or "__ANON__",
            'default_role': self.default_role,
            'keywords': self.keywords,
            'creator_uid': self.creator_uid,
            'create_time': self.create_time,
            'external_data': self.external_data,
            'feeds': self.feeds,
            'map_layers': self.map_layers,
            'invite_only': self.invite_only,
            'expiration': self.expiration,
            'guid': self.guid,
            'uids': self.uids,
            'contents': self.contents,
            'password_protected': self.password_protected,
            'password': self.password
        }

    def to_json(self):
        url = request.url_root.replace("http://", "").replace("https://", "").replace("/", "")
        json = {
            'name': self.name,
            'description': self.description or "",
            'chatRoom': self.chat_room or "",
            'baseLayer': self.base_layer or "",
            'bbox': self.bbox or "",
            'path': self.path or "",
            'classification': self.classification or "",
            'tool': self.tool or "",
            'group': self.group or "__ANON__",
            'defaultRole': self.default_role or "",
            'keywords': self.keywords if self.keywords else [],
            'creatorUid': self.creator_uid or "",
            'createTime': iso8601_string_from_datetime(self.create_time) or "",
            'externalData': self.external_data if self.external_data else [],
            'feeds': self.feeds if self.feeds else [],
            'mapLayers': self.map_layers if self.map_layers else [],
            'inviteOnly': self.invite_only if self.invite_only is not None else False,
            'expiration': self.expiration if self.expiration is not None else -1,
            'guid': self.guid or "",
            'uids': [uid.to_json() for uid in self.uids],
            'contents': [content.to_json() for content in self.contents],
            'passwordProtected': self.password_protected if self.password_protected is not None else False,
            'missionChanges': [mission_change.to_json() for mission_change in self.mission_changes],
            'qr_code': f"{url}:{app.config.get('OTS_SSL_STREAMING_PORT')}:ssl,{url}-{app.config.get('OTS_MARTI_HTTPS_PORT')}-ssl-{self.name},{self.name}",
            'owner': self.owner.to_json() if self.owner else None
        }

        if self.default_role == MissionRole.MISSION_SUBSCRIBER or not self.default_role:
            json['defaultRole'] = MissionRole.SUBSCRIBER_ROLE

        elif self.default_role == MissionRole.MISSION_OWNER:
            json['defaultRole'] = MissionRole.OWNER_ROLE

        else:
            json['defaultRole'] = MissionRole.READ_ONLY_ROLE

        return json
