from dataclasses import dataclass

from opentakserver.extensions import db
from sqlalchemy import String, Float, BLOB
from sqlalchemy.orm import Mapped, mapped_column


@dataclass
class APSchedulerJobs(db.Model):
    __tablename__ = "apscheduler_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    next_run_time: Mapped[float] = mapped_column(Float, nullable=True, index=True)
    job_state: Mapped[bytes] = mapped_column(BLOB, nullable=False)
