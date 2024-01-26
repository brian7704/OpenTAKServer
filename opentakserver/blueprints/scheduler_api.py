from flask import Blueprint, request
from flask_apscheduler import api
from flask_security import roles_accepted

scheduler_api_blueprint = Blueprint('schedule_api_blueprint', __name__)


@scheduler_api_blueprint.route("/api/scheduler/", strict_slashes=False)
@roles_accepted("administrator")
def scheduler_info():
    return api.get_scheduler_info()


@scheduler_api_blueprint.route("/api/scheduler/jobs", strict_slashes=False)
@roles_accepted("administrator")
def get_jobs():
    return api.get_jobs()


@scheduler_api_blueprint.route("/api/scheduler/job/pause", methods=['POST'], strict_slashes=False)
@roles_accepted("administrator")
def pause_job():
    if 'job_id' not in request.json:
        return {'success': False, 'errors': 'Please provide a job_id'}, 400, {'Content-Type': 'application/json'}
    try:
        return api.pause_job(request.json['job_id'])
    except BaseException as e:
        return {'success': False, 'error': str(e)}, 400, {'Content-Type': 'application/json'}


@scheduler_api_blueprint.route("/api/scheduler/job/resume", methods=['POST'], strict_slashes=False)
@roles_accepted("administrator")
def resume_job():
    if 'job_id' not in request.json:
        return {'success': False, 'errors': 'Please provide a job_id'}, 400, {'Content-Type': 'application/json'}
    try:
        return api.resume_job(request.json['job_id'])
    except BaseException as e:
        return {'success': False, 'error': str(e)}, 400, {'Content-Type': 'application/json'}


@scheduler_api_blueprint.route("/api/scheduler/job/run", methods=['POST'], strict_slashes=False)
@roles_accepted("administrator")
def run_job():
    if 'job_id' not in request.json:
        return {'success': False, 'errors': 'Please provide a job_id'}, 400, {'Content-Type': 'application/json'}
    try:
        return api.run_job(request.json['job_id'])
    except BaseException as e:
        return {'success': False, 'error': str(e)}, 400, {'Content-Type': 'application/json'}
