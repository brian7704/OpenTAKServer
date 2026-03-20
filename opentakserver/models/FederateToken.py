from datetime import datetime

from sqlalchemy import JSON, TEXT, DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime


class FederateToken(db.Model):
    __tablename__ = "federate_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    expiration: Mapped[datetime] = mapped_column(DateTime)
    token: Mapped[str] = mapped_column(String(1024))
    share_alerts: Mapped[bool] = mapped_column(Boolean)
    archive: Mapped[bool] = mapped_column(Boolean)
    notes: Mapped[str] = mapped_column(String(255))

    def serialize(self):
        return {
            "name": self.name,
            "expiration": self.expiration,
            "token": self.token,
            "share_alerts": self.share_alerts,
            "archive": self.archive,
            "notes": self.notes,
        }

    def to_json(self):
        def serialize(self):
            return {
                "name": self.name,
                "expiration": iso8601_string_from_datetime(self.expiration),
                "token": self.token,
                "share_alerts": str(self.share_alerts),
                "archive": str(self.archive),
                "notes": self.notes,
            }
