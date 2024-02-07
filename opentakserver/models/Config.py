from opentakserver.extensions import db
from sqlalchemy import String, BLOB
from sqlalchemy.orm import Mapped, mapped_column


class ConfigSettings(db.Model):
    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String)
    value: Mapped[bytes] = mapped_column(BLOB)
