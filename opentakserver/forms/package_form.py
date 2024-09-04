from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired
from wtforms import StringField, IntegerField, FileField
from wtforms.validators import DataRequired, Optional


class PackageForm(FlaskForm):
    platform = StringField(default="Android")
    plugin_type = StringField(default="plugin")
    package_name = StringField(validators=[DataRequired()])
    name = StringField(validators=[DataRequired()])
    version = StringField(validators=[DataRequired()])
    revision_code = IntegerField(validators=[Optional()])
    apk = FileField(validators=[FileRequired()])
    icon = FileField(validators=[Optional()])
    description = StringField(validators=[Optional()])
    apk_hash = StringField(validators=[Optional()])
    os_requirement = StringField(validators=[Optional()])
    tak_prereq = StringField(default="com.atakmap.app@4.10.0.CIV")
