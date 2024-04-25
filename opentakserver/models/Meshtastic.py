from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column


@dataclass
class MeshtasticChannelSettings(db.Model):
    __tablename__ = "meshtastic_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    psk: Mapped[str] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=True)
    uplink_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    downlink_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    position_precision: Mapped[int] = mapped_column(Integer, default=32)  # LOW = 11, MED = 16, HIGH = 32, DISABLED = 0
    lora_region: Mapped[str] = mapped_column(String, default="US")
    lora_hop_limit: Mapped[int] = mapped_column(Integer, default=3)
    lora_tx_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    lora_tx_power: Mapped[int] = mapped_column(Integer, default=30)
    lora_sx126x_rx_boosted_gain: Mapped[bool] = mapped_column(Boolean, default=True)
    modem_preset: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(String, nullable=False)
