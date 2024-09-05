from sqlalchemy import Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opentakserver.extensions import db
from opentakserver.forms.device_profile_form import DeviceProfileForm


class DeviceProfiles(db.Model):
    __tablename__ = "device_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    profile_type: Mapped[str] = mapped_column(String, default="enrollment")
    tool: Mapped[str] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    data_packages = relationship("DataPackage", secondary='device_profiles_data_packages', back_populates='device_profiles')

    def from_wtf(self, form: DeviceProfileForm):
        self.name = form.name
        self.profile_type = form.profile_type
        self.tool = form.tool
        self.active = form.active

    def serialize(self):
        return {
            'name': self.name,
            'profile_type': self.profile_type,
            'tool': self.tool,
            'active': self.active
        }

    def to_json(self):
        return self.serialize()


class DeviceProfilesDataPackages(db.Model):
    __tablename__ = "device_profiles_data_packages"

    device_profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("device_profiles.id"), primary_key=True)
    data_package_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_packages.id"), primary_key=True)
