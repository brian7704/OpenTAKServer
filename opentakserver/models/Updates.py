from opentakserver.extensions import db
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from opentakserver.forms.updates_form import UpdateForm


class Updates(db.Model):
    __tablename__ = "updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String)
    plugin_type: Mapped[str] = mapped_column(String)
    package_name: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    revision_code: Mapped[int] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Integer, nullable=True)
    apk_hash: Mapped[str] = mapped_column(Integer, nullable=True)
    tak_prereq: Mapped[str] = mapped_column(Integer, nullable=True)

    def from_wtform(self, form: UpdateForm):
        self.platform = form.platform
        self.plugin_type = form.plugin_type
        self.package_name = form.package_name
        self.name = form.name
        self.version = form.version
        self.revision_code = form.revision_code
        self.description = form.description
        self.apk_hash = form.apk_hash
        self.tak_prereq = form.tak_prereq

    def serialize(self):
        return {
            'platform': self.platform,
            'plugin_type': self.plugin_type,
            'package_name': self.package_name,
            'name': self.name,
            'version': self.version,
            'revision_code': self.revision_code,
            'description': self.description,
            'apk_hash': self.apk_hash,
            'tak_prereq': self.tak_prereq
        }

    def to_json(self):
        return self.serialize()
