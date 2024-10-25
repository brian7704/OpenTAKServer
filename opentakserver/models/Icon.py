import base64
from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, LargeBinary, String, INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class Icon(db.Model):
    __tablename__ = "icons"

    id: Mapped[int] = mapped_column(INTEGER, primary_key=True)
    iconset_uid: Mapped[str] = mapped_column(String(255), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=True)
    groupName: Mapped[str] = mapped_column(String(255), nullable=True)
    type2525b: Mapped[str] = mapped_column(String(255), nullable=True)
    useCnt: Mapped[int] = mapped_column(Integer, nullable=True)
    bitmap: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    shadow: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    markers = relationship("Marker", back_populates="icon")

    def serialize(self):
        return {
            'iconset_uid': self.iconset_uid,
            'filename': self.filename,
            'groupName': self.groupName,
            'type2525b': self.type2525b,
            'useCnt': self.useCnt,
            'bitmap': 'data:image/png;base64,{}'.format(base64.b64encode(self.bitmap).decode('utf-8')) if self.bitmap else None,
            'shadow': 'data:image/png;base64,{}'.format(base64.b64encode(self.shadow).decode('utf-8')) if self.shadow else None
        }

    def to_json(self):
        return self.serialize()


class IconSets(db.Model):
    __tablename__ = "iconsets"

    id: Mapped[int] = mapped_column(INTEGER, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    uid: Mapped[str] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=True)
    defaultFriendly: Mapped[str] = mapped_column(String(255), nullable=True)
    defaultHostile: Mapped[str] = mapped_column(String(255), nullable=True)
    defaultNeutral: Mapped[str] = mapped_column(String(255), nullable=True)
    defaultUnknown: Mapped[str] = mapped_column(String(255), nullable=True)
    selectedGroup: Mapped[str] = mapped_column(String(255), nullable=True)
