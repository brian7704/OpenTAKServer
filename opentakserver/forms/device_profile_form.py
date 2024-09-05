from flask_wtf import FlaskForm
from flask_wtf.file import FileRequired
from wtforms import StringField, FileField, BooleanField
from wtforms.validators import DataRequired, Optional


class DeviceProfileForm(FlaskForm):
    name = StringField(validators=[DataRequired()])
    enrollment = BooleanField(default=True)
    connection = BooleanField(default=False)
    preference_key = StringField(validators=[Optional()])
    preference_value = StringField(validators=[Optional()])
    tool = StringField(validators=[Optional()])
    active = BooleanField(default=True)
    data_package = FileField(validators=[FileRequired()])
