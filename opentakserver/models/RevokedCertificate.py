from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from opentakserver.extensions import db
from opentakserver.functions import iso8601_string_from_datetime


# Kept separate from the certificates table so a revocation outlives the EUD, user and
# certificate rows it came from. This table is the source of truth for ca.crl.
@dataclass
class RevokedCertificate(db.Model):
    __tablename__ = "revoked_certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    common_name: Mapped[str] = mapped_column(String(255), nullable=True)
    eud_uid: Mapped[str] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_by: Mapped[str] = mapped_column(String(255), nullable=True)

    def to_json(self):
        return {
            "serial_number": self.serial_number,
            "common_name": self.common_name,
            "eud_uid": self.eud_uid,
            "revoked_at": iso8601_string_from_datetime(self.revoked_at),
            "revoked_by": self.revoked_by,
        }
