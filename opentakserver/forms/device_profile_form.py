from flask_babel import gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField
from wtforms.validators import Optional, InputRequired

from opentakserver.forms.Fields import Fields
from opentakserver.functions import false_values


class DeviceProfileForm(FlaskForm, Fields):
    preference_key = StringField(validators=[Optional()], label=gettext("Preference Key"))
    preference_value = StringField(validators=[Optional()], label=gettext("Preference Value"))
    value_class = StringField(validators=[Optional()], label=gettext("Value Type"))
    enrollment = BooleanField(
        false_values=false_values,
        label=gettext("Install on Enrollment"),
        validators=[InputRequired()],
    )
    connection = BooleanField(
        false_values=false_values,
        label=gettext("Install on Connection"),
        validators=[InputRequired()],
    )
    tool = StringField(validators=[Optional()], label=gettext("Tool"))
    active = BooleanField(
        false_values=false_values, label=gettext("Active"), validators=[InputRequired()]
    )
    eud_uid = StringField(validators=[Optional()], label="EUD UID")
