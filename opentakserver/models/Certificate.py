from dataclasses import dataclass
from datetime import datetime

from opentakserver.extensions import db
from sqlalchemy import Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import iso8601_string_from_datetime


@dataclass
class Certificate(db.Model):
    __tablename__ = 'certificates'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    common_name: Mapped[str] = mapped_column(String(255))
    eud_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"), nullable=True)
    data_package_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_packages.id"), nullable=True)
    callsign: Mapped[str] = mapped_column(String(255), nullable=True)
    username: Mapped[str] = mapped_column(String(255), ForeignKey("user.username"), nullable=True)
    expiration_date: Mapped[datetime] = mapped_column(DateTime)
    server_address: Mapped[str] = mapped_column(String(255))
    server_port: Mapped[int] = mapped_column(Integer)
    truststore_filename: Mapped[str] = mapped_column(String(255))
    user_cert_filename: Mapped[str] = mapped_column(String(255))
    csr: Mapped[str] = mapped_column(String(255), nullable=True)
    cert_password: Mapped[str] = mapped_column(String(255))
    user = relationship("User", back_populates="certificate", uselist=False)
    eud = relationship("EUD", cascade="all, delete", back_populates="certificate", uselist=False)
    data_package = relationship("DataPackage", back_populates="certificate", uselist=False)

    def serialize(self):
        return {
            'callsign': self.callsign,
            'expiration_date': self.expiration_date,
            'server_address': self.server_address,
            'server_port': self.server_port,
            'truststore_filename': self.truststore_filename,
            'user_cert_filename': self.user_cert_filename,
            'cert_password': self.cert_password,
            'eud_uid': self.eud_uid
        }

    def to_json(self):
        return {
            'callsign': self.callsign,
            'expiration_date': iso8601_string_from_datetime(self.expiration_date),
            'server_address': self.server_address,
            'server_port': self.server_port,
            'truststore_filename': self.truststore_filename,
            'user_cert_filename': self.user_cert_filename,
            'data_package_filename': self.data_package.filename if self.data_package else None,
            'data_package_hash': self.data_package.hash if self.data_package else None,
            'eud_uid': self.eud_uid
        }
