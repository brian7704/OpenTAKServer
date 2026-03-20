from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, DateTimeField
from wtforms.validators import DataRequired, Optional

from opentakserver.functions import false_values


class FedTokenForm(FlaskForm):
    name = StringField(validators=[DataRequired()])
    expiration = DateTimeField(validators=[DataRequired()])
    token = StringField(validators=[Optional()])
    share_alerts = BooleanField(validators=[Optional()])
    archive = BooleanField(validators=[Optional()])
    notes = StringField(validators=[Optional()])
