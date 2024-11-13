from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column


@dataclass
class MeshtasticChannel(db.Model):
    __tablename__ = "meshtastic_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    psk: Mapped[str] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    uplink_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    downlink_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    position_precision: Mapped[int] = mapped_column(Integer, default=32)  # LOW = 11, MED = 16, HIGH = 32, DISABLED = 0
    lora_region: Mapped[int] = mapped_column(Integer, default=0)
    lora_hop_limit: Mapped[int] = mapped_column(Integer, default=3)
    lora_tx_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    lora_tx_power: Mapped[int] = mapped_column(Integer, default=30)
    lora_sx126x_rx_boosted_gain: Mapped[bool] = mapped_column(Boolean, default=True)
    modem_preset: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    def serialize(self):
        return {
            'psk': self.psk if self.psk else None,
            'name': self.name,
            'uplink_enabled': self.uplink_enabled,
            'downlink_enabled': self.downlink_enabled,
            'position_precision': self.position_precision,
            'lora_region': self.lora_region,
            'lora_hop_limit': self.lora_hop_limit,
            'lora_tx_enabled': self.lora_tx_enabled,
            'lora_tx_power': self.lora_tx_power,
            'lora_sx126x_rx_boosted_gain': self.lora_sx126x_rx_boosted_gain,
            'modem_preset': self.modem_preset,
            'url': self.url
        }

    def to_json(self):
        preset = "LONG_FAST"
        if self.modem_preset == 1:
            preset = "LONG_SLOW"
        elif self.modem_preset == 2:
            preset = "VERY_LONG_SLOW"
        elif self.modem_preset == 3:
            preset = "MEDIUM_SLOW"
        elif self.modem_preset == 4:
            preset = "MEDIUM_FAST"
        elif self.modem_preset == 5:
            preset = "SHORT_SLOW"
        elif self.modem_preset == 6:
            preset = "SHORT_FAST"
        elif self.modem_preset == 7:
            preset = "LONG_MODERATE"

        region = "UNSET"
        if self.lora_region == 1:
            region = "US"
        elif self.lora_region == 2:
            region = "EU_433"
        elif self.lora_region == 3:
            region = "EU_868"
        elif self.lora_region == 4:
            region = "CN"
        elif self.lora_region == 5:
            region = "JP"
        elif self.lora_region == 6:
            region = "ANZ"
        elif self.lora_region == 7:
            region = "KR"
        elif self.lora_region == 8:
            region = "TW"
        elif self.lora_region == 9:
            region = "RU"
        elif self.lora_region == 10:
            region = "IN"
        elif self.lora_region == 11:
            region = "NZ_865"
        elif self.lora_region == 12:
            region = "TH"
        elif self.lora_region == 13:
            region = "LORA_24"
        elif self.lora_region == 14:
            region = "UA_433"
        elif self.lora_region == 15:
            region = "UA_868"
        elif self.lora_region == 16:
            region = "MY_433"
        elif self.lora_region == 17:
            region = "MY_919"
        elif self.lora_region == 18:
            region = "SG_923"


        return {
            'psk': self.psk if self.psk else None,
            'name': self.name,
            'uplink_enabled': self.uplink_enabled,
            'downlink_enabled': self.downlink_enabled,
            'position_precision': self.position_precision,
            'lora_region': region,
            'lora_hop_limit': self.lora_hop_limit,
            'lora_tx_enabled': self.lora_tx_enabled,
            'lora_tx_power': self.lora_tx_power,
            'lora_sx126x_rx_boosted_gain': self.lora_sx126x_rx_boosted_gain,
            'modem_preset': preset,
            'url': self.url
        }
