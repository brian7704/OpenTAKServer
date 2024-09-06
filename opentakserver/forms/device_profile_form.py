from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import DataRequired, Optional

from opentakserver.functions import false_values


class DeviceProfileForm(FlaskForm):
    preference_key = StringField(validators=[DataRequired()])
    preference_value = StringField(validators=[DataRequired()])
    value_class = StringField(validators=[DataRequired()])
    enrollment = BooleanField(false_values=false_values)
    connection = BooleanField(false_values=false_values)
    tool = StringField(validators=[Optional()])
    active = BooleanField(false_values=false_values)
