from flask import Blueprint, request
from flask_security import auth_required

from opentakserver.extensions import db
from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.models.Group import Group

group_api = Blueprint("group_api", __name__)


@group_api.route('/api/groups')
@auth_required()
def get_groups():
    query = db.session.query(Group)
    query = search(query, Group, 'group_name')
    query = search(query, Group, 'direction')
    query = search(query, Group, 'group_type')
    query = search(query, Group, 'bitpos')
    query = search(query, Group, 'active')

    return paginate(query)
