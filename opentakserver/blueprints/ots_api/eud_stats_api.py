from flask import Blueprint
from flask_security import auth_required

from opentakserver.blueprints.ots_api.api import search
from opentakserver.extensions import db
from opentakserver.models.EUDStats import EUDStats

eud_stats_blueprint = Blueprint("eud_stats_blueprint", __name__)


@eud_stats_blueprint.route("/api/eud_stats")
@auth_required()
def get_stats():

    query = db.session.query(EUDStats)
    query = search(query, EUDStats, "eud_uid")
    # TODO: Implement date range search
    # query = search(query, EUDStats, 'from')
    # query = search(query, EUDStats, 'to')

    rows = db.session.execute(query.order_by(EUDStats.id.desc()).limit(50)).all()

    results = {"results": [], "total_pages": 1, "current_page": 1, "per_page": len(rows)}

    for row in rows:
        results["results"].insert(0, row[0].to_json())

    return results
