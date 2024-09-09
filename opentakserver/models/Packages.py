import base64
import os.path
from pathlib import Path

from werkzeug.utils import secure_filename

from sqlalchemy import Integer, String, BLOB, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from flask import current_app as app, request

from opentakserver.extensions import db
from opentakserver.forms.package_form import PackageForm


class Packages(db.Model):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String)
    plugin_type: Mapped[str] = mapped_column(String)
    package_name: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    file_name: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    revision_code: Mapped[int] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Integer, nullable=True)
    apk_hash: Mapped[str] = mapped_column(Integer, nullable=True)
    os_requirement: Mapped[str] = mapped_column(Integer, nullable=True)
    tak_prereq: Mapped[str] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer)
    icon: Mapped[bytes] = mapped_column(BLOB, nullable=True)
    icon_filename: Mapped[str] = mapped_column(String, nullable=True)
    install_on_enrollment: Mapped[bool] = mapped_column(Boolean, default=False)
    install_on_connection: Mapped[bool] = mapped_column(Boolean, default=False)

    def from_wtform(self, form: PackageForm):
        self.platform = form.platform.data
        self.plugin_type = form.plugin_type.data
        self.package_name = form.package_name.data
        self.name = form.name.data
        self.file_name = secure_filename(form.apk.data.filename)
        self.version = form.version.data
        self.revision_code = form.revision_code.data
        self.description = form.description.data
        self.apk_hash = form.apk_hash.data
        self.os_requirement = form.os_requirement.data
        self.tak_prereq = form.tak_prereq.data
        self.file_size = Path(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", self.file_name)).stat().st_size
        self.icon = request.files['icon'].stream.read()
        self.icon_filename = secure_filename(request.files['icon'].filename) if 'icon' in request.files else None
        self.install_on_enrollment = form.install_on_enrollment.data
        self.install_on_connection = form.install_on_connection.data

    def serialize(self):
        return {
            'platform': self.platform,
            'plugin_type': self.plugin_type,
            'package_name': self.package_name,
            'name': self.name,
            'file_name': self.file_name,
            'version': self.version,
            'revision_code': self.revision_code,
            'description': self.description,
            'apk_hash': self.apk_hash,
            'os_requirement': self.os_requirement,
            'tak_prereq': self.tak_prereq,
            'file_size': self.file_size,
            'icon': self.icon,
            'icon_filename': self.icon_filename,
            'install_on_enrollment': self.install_on_enrollment,
            'install_on_connection': self.install_on_connection
        }

    def to_json(self):
        data = self.serialize()
        data['icon'] = base64.urlsafe_b64encode(self.icon)
        return data
