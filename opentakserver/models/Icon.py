import base64
from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import Integer, String, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class Icon(db.Model):
    __tablename__ = "icons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iconset_uid: Mapped[str] = mapped_column(String, nullable=True)
    filename: Mapped[str] = mapped_column(String, nullable=True)
    groupName: Mapped[str] = mapped_column(String, nullable=True)
    type2525b: Mapped[str] = mapped_column(String, nullable=True)
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
