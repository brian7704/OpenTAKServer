from dataclasses import dataclass

from extensions import db
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column


@dataclass
class MediaMTXPath(db.Model):
    __tablename__ = 'mediamtx_paths'

    path: Mapped[str] = mapped_column(String, primary_key=True)
    settings: Mapped[str] = mapped_column(String)
