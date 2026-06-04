from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, IntegerField, FileField
from wtforms.validators import DataRequired, Optional

from opentakserver.functions import false_values


class FederateForm(FlaskForm):
    name = StringField(validators=[DataRequired()])
    shared_alerts = BooleanField(default=False, false_values=false_values, validators=[Optional()])
    archive = BooleanField(default=False, false_values=false_values, validators=[Optional()])
    federate_group_matching = BooleanField(
        default=False, false_values=false_values, validators=[Optional()]
    )
    automatic_group_matching = BooleanField(
        default=False, false_values=false_values, validators=[Optional()]
    )
    fallback_group_matching = BooleanField(
        default=False, false_values=false_values, validators=[Optional()]
    )
    max_hops = IntegerField(default=-1, validators=[Optional()])
    use_group_hop_limiting = BooleanField(
        default=False, false_values=false_values, validators=[Optional()]
    )
    notes = StringField(validators=[Optional()])
    certificate_file = FileField(validators=[DataRequired()])
    issuer = StringField(validators=[Optional()])
    subject = StringField(validators=[Optional()])
    serial_number = StringField(validators=[Optional()])
