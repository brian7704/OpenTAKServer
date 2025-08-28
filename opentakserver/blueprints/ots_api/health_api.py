from flask import Blueprint, jsonify
from flask_security import auth_required

# Blueprint for health endpoints
health_api = Blueprint("health_api", __name__)


@health_api.route("/api/health/ots")
@auth_required()
def health_ots():
    """Placeholder health check for OTS."""
    return jsonify({"status": "ok"})


@health_api.route("/api/health/cot")
@auth_required()
def health_cot():
    """Placeholder health check for CoT."""
    return jsonify({"status": "ok"})


@health_api.route("/api/health/eud")
@auth_required()
def health_eud():
    """Placeholder health check for EUD."""
    return jsonify({"status": "ok"})
