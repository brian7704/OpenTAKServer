from sqlalchemy import Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db
from opentakserver.forms.device_profile_form import DeviceProfileForm


class DeviceProfiles(db.Model):
    __tablename__ = "device_profiles"

    preference_key: Mapped[str] = mapped_column(String, primary_key=True)
    preference_value: Mapped[str] = mapped_column(String)
    value_class: Mapped[str] = mapped_column(String)
    enrollment: Mapped[bool] = mapped_column(Boolean, default=True)
    connection: Mapped[bool] = mapped_column(Boolean, default=False)
    tool: Mapped[str] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    def from_wtf(self, form: DeviceProfileForm):
        self.preference_key = form.preference_key.data
        self.preference_value = form.preference_value.data
        self.value_class = form.value_class.data
        self.enrollment = form.enrollment.data
        self.connection = form.connection.data
        self.tool = form.tool.data
        self.active = form.active.data

    def serialize(self):
        return {
            'preference_key': self.preference_key,
            'preference_value': self.preference_value,
            'value_class': self.value_class,
            'enrollment': self.enrollment,
            'connection': self.connection,
            'tool': self.tool,
            'active': self.active
        }

    def to_json(self):
        return self.serialize()
