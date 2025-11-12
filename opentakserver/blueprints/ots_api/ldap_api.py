from flask import current_app as app, request, Blueprint
from flask_ldap3_login.forms import LDAPLoginForm
from flask_security import login_user, current_user
from flask_security.utils import base_render_json
from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.extensions import ldap_manager
from opentakserver.models.user import User
from opentakserver.extensions import logger

ldap_blueprint = Blueprint('ldap_blueprint', __name__)


@ldap_manager.save_user
def save_user(dn: str, username: str, data, groups):
    """
    This callback will check Flask-Security's database for a user. If the user exists, all roles are removed. If
    the user doesn't exist, it is created. Finally, the LDAP groups the user belongs  are then added as Flask-Security roles.
    This allows admins to change user groups and have them work immediately on the next login.

    :param dn: User's LDAP Distinguished Name
    :param username: The Username
    :param data: All LDAP attributes for the user
    :param groups: A list of groups the user belongs to
    :return: User object
    """

    user: User = app.security.datastore.find_user(username=username)
    if user:
        roles = user.roles
        for role in roles:
            app.security.datastore.remove_role_from_user(user, role)
    else:
        user = app.security.datastore.create_user(username=username, password=None)

    is_admin = False
    for group in groups:
        if group['cn'] == app.config.get("OTS_LDAP_ADMIN_GROUP"):
            is_admin = True
        elif group['cn'].startswith(app.config.get("OTS_LDAP_PREFERENCE_ATTRIBUTE_PREFIX")) and not (group['cn'].lower().endswith("_read") or group['cn'].lower().endswith("_write")):
            logger.debug(f"Adding {group['cn']} role to {user.username}")
            app.security.datastore.add_role_to_user(user, app.security.datastore.find_or_create_role(group['cn']))

    if not is_admin:
        app.security.datastore.add_role_to_user(user, 'user')
    else:
        app.security.datastore.add_role_to_user(user, 'administrator')

    app.security.datastore.commit()
    return user


@ldap_blueprint.route("/api/ldap_login", methods=["POST"])
def ldap_login():
    form = LDAPLoginForm(formdata=ImmutableMultiDict(request.json))

    # LDAPLoginForm.validate() will call save_user()
    if form.validate():
        login_user(form.user, app.config.get("SECURITY_DEFAULT_REMEMBER_ME"), authn_via=["ldap"])
        payload = {"identity_attributes": {"ldap": {}}}
        return base_render_json(form, include_auth_token=True, additional=payload)

    else:
        return base_render_json(form)
