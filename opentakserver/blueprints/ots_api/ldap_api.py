from flask import current_app as app, request, Blueprint
from flask_ldap3_login.forms import LDAPLoginForm
from flask_security import login_user
from flask_security.utils import base_render_json
from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.extensions import ldap_manager
from opentakserver.models.user import User

ldap_blueprint = Blueprint('ldap_blueprint', __name__)


@ldap_manager.save_user
def save_user(dn: str, username: str, data, groups):
    user: User = app.security.datastore.find_user(username=username)
    if user:
        roles = user.roles
        for role in roles:
            if role == app.config.get("OTS_LDAP_ADMIN_GROUP"):
                role = "administrator"

            app.security.datastore.remove_role_from_user(user, role)
    else:
        user = app.security.datastore.create_user(username=username, password=None)

    for group in groups:
        app.security.datastore.add_role_to_user(user, app.security.datastore.find_or_create_role(group['cn']))

    app.security.datastore.commit()
    return user


@ldap_blueprint.route("/api/ldap_login", methods=["POST"])
def ldap_login():
    form = LDAPLoginForm(formdata=ImmutableMultiDict(request.json))

    if form.validate():
        login_user(form.user, app.config.get("SECURITY_DEFAULT_REMEMBER_ME"), authn_via=["ldap"])
        payload = {"identity_attributes": {"ldap": {}}}
        return base_render_json(form, include_auth_token=True, additional=payload)

    else:
        return base_render_json(form)
