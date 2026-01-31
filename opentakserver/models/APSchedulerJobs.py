from dataclasses import dataclass

from sqlalchemy import Float, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from opentakserver.extensions import db


@dataclass
class APSchedulerJobs(db.Model):
    __tablename__ = "apscheduler_jobs"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    next_run_time: Mapped[float] = mapped_column(Float, nullable=True, index=True)
    job_state: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
