from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, BooleanField, FloatField
from wtforms.validators import DataRequired, UUID


class ZmistForm(FlaskForm):
    i = StringField()
    m = StringField()
    s = StringField()
    t = StringField()
    title = StringField()
    z = StringField()
