from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired, FileAllowed
from wtforms import StringField, FileField, BooleanField
from wtforms.validators import Optional, DataRequired
from opentakserver.functions import false_values
import semver


class PackageForm(FlaskForm):
    platform = StringField(default="Android")
    plugin_type = StringField(default="plugin")
    apk = FileField(validators=[FileRequired(), FileAllowed(['apk'])])
    icon = FileField(validators=[Optional()])
    description = StringField(validators=[Optional()])
    install_on_enrollment = BooleanField(false_values=false_values)
    install_on_connection = BooleanField(false_values=false_values)
    atak_version = StringField(validators=[Optional()])


class PackageUpdateForm(FlaskForm):
    package_name = StringField(validators=[DataRequired()])
    install_on_enrollment = BooleanField(false_values=false_values)
    install_on_connection = BooleanField(false_values=false_values)
    atak_version = StringField(validators=[Optional()])

    @staticmethod
    def validate_atak_version(form, field):
        # Plugins for ATAK 5.4.0 and older won't have an atak_version
        if field.data:
            # semver.Version.parse() will raise ValueError if it's not a semver string.
            # Flask-wtf will mark the data as invalid when ValueError is raised
            semver.Version.parse(field.data)
