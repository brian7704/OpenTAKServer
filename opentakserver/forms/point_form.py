from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, BooleanField, FloatField, DateTimeField
from wtforms.validators import DataRequired, UUID, NumberRange, Optional


class PointForm(FlaskForm):
    latitude = FloatField(validators=[DataRequired(), NumberRange(min=-90, max=90)])
    longitude = FloatField(validators=[DataRequired(), NumberRange(min=-180, max=180)])
    ce = FloatField(default=9999999.0)
    hae = FloatField(default=9999999.0)
    le = FloatField(default=9999999.0)
    course = FloatField(default=0.0, validators=[NumberRange(min=0)])
    speed = FloatField(default=0.0, validators=[NumberRange(min=0)])
    location_source = StringField()
    battery = FloatField(validators=[NumberRange(min=0, max=100), Optional()], default=None)
    timestamp = DateTimeField(format="%Y-%m-%dT%H:%M:%S.%fZ", validators=[DataRequired()])
    azimuth = FloatField(validators=[NumberRange(min=0, max=360), Optional()], default=None)
    fov = FloatField(validators=[NumberRange(min=0, max=360), Optional()], default=None)
