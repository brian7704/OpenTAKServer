from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import Optional

from opentakserver.functions import false_values


class DeviceProfileForm(FlaskForm):
    preference_key = StringField(validators=[Optional()])
    preference_value = StringField(validators=[Optional()])
    value_class = StringField(validators=[Optional()])
    enrollment = BooleanField(false_values=false_values)
    connection = BooleanField(false_values=false_values)
    tool = StringField(validators=[Optional()])
    active = BooleanField(false_values=false_values)
