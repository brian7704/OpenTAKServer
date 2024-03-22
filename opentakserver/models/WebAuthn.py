from opentakserver.extensions import db
from flask_security.models import fsqla_v3 as fsqla


class WebAuthn(db.Model, fsqla.FsWebAuthnMixin):
    pass
