from flask_wtf import FlaskForm
from wtforms import StringField


class ZmistForm(FlaskForm):
    i = StringField()
    m = StringField()
    s = StringField()
    t = StringField()
    title = StringField()
    z = StringField()
