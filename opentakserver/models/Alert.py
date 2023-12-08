from opentakserver.extensions import Base
from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Alert(Base):
    __tablename__ = 'alerts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String, ForeignKey("eud.id"))
    start_time: Mapped[str] = mapped_column(String)
    cancel_time: Mapped[str] = mapped_column(String, nullable=True)
    alert_type: Mapped[str] = mapped_column(String)
    point_id: Mapped[int] = mapped_column(Integer, ForeignKey("points.id"), nullable=True)
    cot_id: Mapped[int] = mapped_column(Integer, ForeignKey("cot.id"), nullable=True)
