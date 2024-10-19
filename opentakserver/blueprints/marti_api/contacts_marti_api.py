from flask import Blueprint, request, jsonify
from opentakserver.extensions import db, logger
from opentakserver.models.EUD import EUD

contacts_api = Blueprint("contacts_api", __name__)


@contacts_api.route('/Marti/api/contacts/all')
def get_all_contacts():
    logger.info(request.headers)
    logger.info(request.data)

    euds = db.session.execute(db.session.query(EUD)).all()

    response = []

    for eud in euds:
        eud = eud[0]
        team_name = eud.team.name if eud.team else 'Cyan'
        team_role = eud.team_role or 'Team Member'
        username = eud.user.username if eud.user else ''
        response.append(
            {'filterGroups': [], 'notes': username, 'callsign': eud.callsign, 'team': team_name,
             'role': team_role, 'takv': f"{eud.platform} {eud.version}", 'uid': eud.uid}
        )

    return jsonify(response)
