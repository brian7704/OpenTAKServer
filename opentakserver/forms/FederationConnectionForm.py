from flask_wtf import FlaskForm
from wtforms import StringField, IntegerRangeField, BooleanField, IntegerField
from wtforms.validators import DataRequired, NumberRange, Optional

from opentakserver.functions import false_values


class FederationConnectionForm(FlaskForm):
    display_name = StringField(validators=[DataRequired()])
    address = StringField(validators=[DataRequired()])
    port = IntegerRangeField(
        default=9001, validators=[DataRequired(), NumberRange(min=1, max=65535)]
    )
    enabled = BooleanField(default=True, validators=[Optional()])
    protocol_version = StringField(default="2", validators=[Optional()])
    reconnect_interval = IntegerField(default=30, validators=[Optional()])
    unlimited_retries = BooleanField(
        default=False, false_values=false_values, validators=[Optional()]
    )
    max_retries = IntegerField(default=3, validators=[Optional()])
    federate_id: IntegerField(validators=[DataRequired()])
    fallback_connection = IntegerField(validators=[Optional()])
    use_token_auth = BooleanField(default=False, false_values=false_values, validators=[Optional()])
    auth_token_type = StringField(default=None, validators=[Optional()])
    auth_token = StringField(default=None, validators=[Optional()])
    last_error = StringField(default=None, validators=[Optional()])
    description = StringField(default=None, validators=[Optional()])
