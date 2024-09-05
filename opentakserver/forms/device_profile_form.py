from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired
from wtforms import StringField, FileField, BooleanField
from wtforms.validators import DataRequired, Optional


class DeviceProfileForm(FlaskForm):
    name = StringField(validators=[DataRequired()])
    profile_type = StringField(default="enrollment")
    tool = StringField(validators=[Optional()])
    active = BooleanField(default=True)
    data_package = FileField(validators=[FileRequired()])
