from flask import Blueprint, jsonify, request
from flask_security import auth_required

from opentakserver.health.cot_parser import (
    compute_status,
    find_errors,
    query_systemd,
    rabbitmq_check,
    tail_ots_log_for_cot_parser_entries,
    current_timestamp,
)

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
    """Health check for the CoT parser service."""
    service_state = query_systemd()
    log_lines = tail_ots_log_for_cot_parser_entries()
    log_errors = find_errors(log_lines)
    rabbit_ok = rabbitmq_check()

    status = compute_status(service_state, log_errors, rabbit_ok)
    status["timestamp"] = current_timestamp()

    strict = request.args.get("strict", "false").lower() == "true"
    code = 200
    if strict and status["overall"] != "healthy":
        code = 503

    return jsonify(status), code


@health_api.route("/api/health/eud")
@auth_required()
def health_eud():
    """Placeholder health check for EUD."""
    return jsonify({"status": "ok"})

