from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired, FileAllowed
from wtforms import StringField, FileField, BooleanField
from wtforms.validators import Optional, DataRequired
from opentakserver.functions import false_values


class PackageForm(FlaskForm):
    platform = StringField(default="Android")
    plugin_type = StringField(default="plugin")
    apk = FileField(validators=[FileRequired(), FileAllowed(['apk'])])
    icon = FileField(validators=[Optional()])
    description = StringField(validators=[Optional()])
    install_on_enrollment = BooleanField(false_values=false_values)
    install_on_connection = BooleanField(false_values=false_values)


class PackageUpdateForm(FlaskForm):
    package_name = StringField(validators=[DataRequired()])
    install_on_enrollment = BooleanField(false_values=false_values)
    install_on_connection = BooleanField(false_values=false_values)
