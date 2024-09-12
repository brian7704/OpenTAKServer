import os
from datetime import datetime

from flask import request, current_app as app
from sqlalchemy import String, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from werkzeug.utils import secure_filename

from opentakserver.extensions import db
from opentakserver.forms.device_profile_form import DeviceProfileForm
from opentakserver.functions import iso8601_string_from_datetime


class DeviceProfiles(db.Model):
    __tablename__ = "device_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    preference_key: Mapped[str] = mapped_column(String, nullable=True)
    preference_value: Mapped[str] = mapped_column(String, nullable=True)
    value_class: Mapped[str] = mapped_column(String, nullable=True)
    filename: Mapped[str] = mapped_column(String, nullable=True)
    enrollment: Mapped[bool] = mapped_column(Boolean, default=True)
    connection: Mapped[bool] = mapped_column(Boolean, default=False)
    tool: Mapped[str] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    publish_time: Mapped[datetime] = mapped_column(DateTime)

    def from_wtf(self, form: DeviceProfileForm):
        self.preference_key = form.preference_key.data
        self.preference_value = form.preference_value.data
        self.value_class = f"class java.lang.{form.value_class.data.split('.')[-1]}"
        if form.file.data:
            self.filename = secure_filename(form.file.data.filename)
            request.files['filename'].save(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", self.filename))
        else:
            self.filename = None
        self.enrollment = form.enrollment.data
        self.connection = form.connection.data
        self.tool = form.tool.data
        self.active = form.active.data
        self.publish_time = datetime.now()

    def serialize(self):
        return {
            'preference_key': self.preference_key,
            'preference_value': self.preference_value,
            'value_class': self.value_class,
            'filename': self.filename,
            'enrollment': self.enrollment,
            'connection': self.connection,
            'tool': self.tool,
            'active': self.active,
            'publish_time': self.publish_time
        }

    def to_json(self):
        return_value = self.serialize()
        return_value['publish_time'] = iso8601_string_from_datetime(self.publish_time)
        return return_value
