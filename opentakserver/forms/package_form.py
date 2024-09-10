from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired
from wtforms import StringField, IntegerField, FileField, BooleanField
from wtforms.validators import DataRequired, Optional
from opentakserver.functions import false_values


class PackageForm(FlaskForm):
    platform = StringField(default="Android")
    plugin_type = StringField(default="plugin")
    apk = FileField(validators=[FileRequired()])
    icon = FileField(validators=[Optional()])
    description = StringField(validators=[Optional()])
    install_on_enrollment = BooleanField(false_values=false_values)
    install_on_connection = BooleanField(false_values=false_values)
