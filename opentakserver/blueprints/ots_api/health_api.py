from flask import Blueprint, jsonify, request
from flask_security import auth_required

from opentakserver.health import cot_parser, eud_handler

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
    service_state = cot_parser.query_systemd()
    log_lines = cot_parser.tail_ots_log_for_cot_parser_entries()
    log_errors = cot_parser.find_errors(log_lines)
    rabbit_ok = cot_parser.rabbitmq_check()

    status = cot_parser.compute_status(service_state, log_errors, rabbit_ok)
    status["timestamp"] = cot_parser.current_timestamp()

    strict = request.args.get("strict", "false").lower() == "true"
    code = 200
    if strict and status["overall"] != "healthy":
        code = 503

    return jsonify(status), code


@health_api.route("/api/health/eud")
@auth_required()
def health_eud():
    """Health check for the EUD handler service."""
    service_state = eud_handler.query_systemd()
    log_lines = eud_handler.tail_ots_log_for_eud_handler_entries()
    log_errors = eud_handler.find_errors(log_lines)
    rabbit_ok = eud_handler.rabbitmq_check()

    status = eud_handler.compute_status(service_state, log_errors, rabbit_ok)
    status["timestamp"] = eud_handler.current_timestamp()

    strict = request.args.get("strict", "false").lower() == "true"
    code = 200
    if strict and status["overall"] != "healthy":
        code = 503

    return jsonify(status), code

