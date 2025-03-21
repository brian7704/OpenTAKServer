from dataclasses import dataclass

from opentakserver.extensions import db
from opentakserver.functions import bytes_to_gigabytes, bytes_to_megabytes
from sqlalchemy import Integer, String, ForeignKey, DateTime, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.functions import iso8601_string_from_datetime


@dataclass
class EUDStats(db.Model):
    __tablename__ = "eud_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    eud_uid: Mapped[str] = mapped_column(String(255), ForeignKey("euds.uid", ondelete="CASCADE"), nullable=False)
    heap_free_size: Mapped[int] = mapped_column(BigInteger, nullable=True)
    app_framerate: Mapped[int] = mapped_column(Integer, nullable=True)
    storage_total: Mapped[int] = mapped_column(BigInteger, nullable=True)
    heap_current_size: Mapped[int] = mapped_column(Integer, nullable=True)
    battery: Mapped[int] = mapped_column(Integer, nullable=True)
    battery_temp: Mapped[int] = mapped_column(Integer, nullable=True)
    deviceDataRx: Mapped[int] = mapped_column(BigInteger, nullable=True)
    heap_max_size: Mapped[int] = mapped_column(BigInteger, nullable=True)
    storage_available: Mapped[int] = mapped_column(BigInteger, nullable=True)
    deviceDataTx: Mapped[int] = mapped_column(BigInteger, nullable=True)
    ip_address: Mapped[str] = mapped_column(String(255), nullable=True)
    battery_status: Mapped[str] = mapped_column(String(255), nullable=True)
    eud = relationship("EUD", back_populates="stats", uselist=False)

    def serialize(self):
        return {
            "timestamp": self.timestamp,
            "eud_uid": self.eud_uid,
            "heap_free_size": self.heap_free_size,
            "app_framerate": self.app_framerate,
            "storage_total": self.storage_total,
            "heap_current_size": self.heap_current_size,
            "battery": self.battery,
            "deviceDataRx": self.deviceDataRx,
            "heap_max_size": self.heap_max_size,
            "storage_available": self.storage_available,
            "deviceDataTx": self.deviceDataTx,
            "ip_address": self.ip_address,
            "battery_status": self.battery_status
        }

    def to_json(self):
        return {
            "timestamp": iso8601_string_from_datetime(self.timestamp),
            "eud_uid": self.eud_uid,
            "heap_free_size": bytes_to_megabytes(self.heap_free_size),
            "app_framerate": self.app_framerate,
            "storage_total": bytes_to_gigabytes(self.storage_total),
            "heap_current_size": bytes_to_megabytes(self.heap_current_size),
            "battery": self.battery,
            "deviceDataRx": bytes_to_megabytes(self.deviceDataRx),
            "heap_max_size": bytes_to_megabytes(self.heap_max_size),
            "storage_available": bytes_to_gigabytes(self.storage_available),
            "deviceDataTx": bytes_to_megabytes(self.deviceDataTx),
            "ip_address": self.ip_address,
            "battery_status": self.battery_status
        }
