from dataclasses import dataclass

from extensions import db
from sqlalchemy import Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship


@dataclass
class Certificate(db.Model):
    __tablename__ = 'certificates'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    eud_uid: Mapped[str] = mapped_column(Integer, ForeignKey("eud.uid"), unique=True)
    data_package_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_packages.id"))
    callsign: Mapped[str] = mapped_column(String, unique=True)
    expiration_date: Mapped[str] = mapped_column(String)
    server_address: Mapped[str] = mapped_column(String)
    server_port: Mapped[int] = mapped_column(Integer)
    truststore_filename: Mapped[str] = mapped_column(String)
    user_cert_filename: Mapped[str] = mapped_column(String)
    cert_password: Mapped[str] = mapped_column(String)
    eud = relationship("EUD", back_populates="certificate", uselist=False)
    data_package = relationship("DataPackage", back_populates="certificate", uselist=False)

    def serialize(self):
        return {
            'certificate': {
                'callsign': self.callsign,
                'expiration_date': self.expiration_date,
                'server_address': self.server_address,
                'server_port': self.server_port,
                'truststore_filename': self.truststore_filename,
                'user_cert_filename': self.user_cert_filename,
                'cert_password': self.cert_password,
                'data_package_filename': self.data_package.filename,
                'eud_uid': self.eud_uid
            }
        }
