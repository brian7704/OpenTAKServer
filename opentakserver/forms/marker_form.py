from wtforms import BooleanField, DateTimeField, IntegerField, StringField
from wtforms.validators import UUID, DataRequired

from opentakserver.forms.point_form import PointForm


class MarkerForm(PointForm):
    uid = StringField(validators=[DataRequired(), UUID()])
    callsign = StringField(validators=[DataRequired()])
    affiliation = StringField()
    battle_dimension = StringField()
    readiness = BooleanField()
    argb = IntegerField()
    color_hex = StringField()
    iconset_path = StringField()
    parent_callsign = StringField()
    production_time = DateTimeField(format="%Y-%m-%dT%H:%M:%S.%fZ")
    relation = StringField()
    relation_type = StringField()
    location_source = StringField()
    remarks = StringField()
    mil_std_2525c = StringField()
