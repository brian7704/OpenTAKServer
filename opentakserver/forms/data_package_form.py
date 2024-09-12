from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import Optional, DataRequired

from opentakserver.functions import false_values


class DataPackageUpdateForm(FlaskForm):
    hash = StringField(validators=[DataRequired()])
    install_on_enrollment = BooleanField(validators=[Optional()], false_values=false_values)
    install_on_connection = BooleanField(validators=[Optional()], false_values=false_values)
