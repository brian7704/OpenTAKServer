from apscheduler.jobstores.base import ConflictingIdError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore


class SQLJobStore(SQLAlchemyJobStore):
    def add_job(self, job):
        try:
            super().add_job(job)
        except ConflictingIdError:
            pass
