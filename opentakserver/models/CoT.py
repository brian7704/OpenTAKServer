from opentakserver.extensions import Base
from sqlalchemy import Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column


class CoT(Base):
    __tablename__ = "cot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    how: Mapped[str] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, nullable=True)
    sender_callsign: Mapped[str] = mapped_column(String, nullable=True)
    sender_device_name: Mapped[str] = mapped_column(String, nullable=True)
    recipients: Mapped[JSON] = mapped_column(JSON, nullable=True)
    xml: Mapped[str] = mapped_column(String)
