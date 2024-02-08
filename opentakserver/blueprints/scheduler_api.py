from apscheduler.triggers.combining import AndTrigger, OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from flask import Blueprint, request, jsonify
from flask_apscheduler import api
from flask_security import roles_accepted
from opentakserver.extensions import apscheduler

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
        #  0 == STATE_STOPPED
        if apscheduler.state == 0:
            apscheduler.start()
        #  2 == STATE_PAUSED
        elif apscheduler.state == 2:
            apscheduler.resume()

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


@scheduler_api_blueprint.route("/api/scheduler/job/modify", methods=['POST'], strict_slashes=False)
@roles_accepted("administrator")
def modify_job():
    if 'job_id' not in request.json:
        return {'success': False, 'errors': 'Please provide a job_id'}, 400, {'Content-Type': 'application/json'}
    try:
        job_id = request.json.pop('job_id')
        trigger = request.json.pop('trigger')
        job = apscheduler.get_job(job_id)
        if trigger == 'interval':
            trigger = IntervalTrigger(**request.json)
        elif trigger == 'cron':
            trigger = CronTrigger(**request.json)
        elif trigger == 'date':
            trigger = DateTrigger(**request.json)
        elif trigger == 'and':
            trigger = AndTrigger(**request.json)
        elif trigger == 'or':
            trigger = OrTrigger(**request.json)
        else:
            return jsonify({'success': False, 'error': 'Invalid trigger: {}'.format(trigger)}), 400

        job.modify(trigger=trigger)
        return jsonify({'success': True})
    except BaseException as e:
        return {'success': False, 'error': str(e)}, 400, {'Content-Type': 'application/json'}
