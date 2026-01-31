from flask_wtf import FlaskForm
from wtforms import BooleanField, FloatField, IntegerField, StringField
from wtforms.validators import UUID, DataRequired


class ZmistForm(FlaskForm):
    i = StringField()
    m = StringField()
    s = StringField()
    t = StringField()
    title = StringField()
    z = StringField()
