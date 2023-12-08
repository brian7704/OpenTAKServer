from opentakserver.extensions import Base
from sqlalchemy import Integer, String, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


class CoT(Base):
    __tablename__ = "cot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    how: Mapped[str] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=True)
    sender_callsign: Mapped[str] = mapped_column(String)
    sender_device_name: Mapped[str] = mapped_column(String, nullable=True)
    sender_uid: Mapped[str] = mapped_column(String, ForeignKey("eud.uid"), nullable=True)
    recipients: Mapped[JSON] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[str] = mapped_column(String)
    xml: Mapped[str] = mapped_column(String)
    eud: Mapped["EUD"] = relationship(back_populates="cots")
