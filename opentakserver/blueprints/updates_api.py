import os

from flask import current_app as app, request, Blueprint, jsonify, send_from_directory
from flask_security import roles_accepted

from opentakserver.forms.updates_form import UpdateForm
from opentakserver.models.Updates import Updates
from opentakserver.extensions import db

from werkzeug.datastructures import ImmutableMultiDict
from werkzeug.utils import secure_filename

updates_blueprint = Blueprint('updates_api_blueprint', __name__)


@updates_blueprint.route('/api/updates')
@roles_accepted("administrator")
def get_updates():
    return


@updates_blueprint.route('/api/updates', methods=['POST'])
@roles_accepted("administrator")
def add_update():
    form = UpdateForm(formdata=ImmutableMultiDict(request.json))
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors()}), 400

    update = Updates()
    update.from_wtform(form)
    db.session.add(update)
    db.session.commit()

    apk_filename = secure_filename(form.apk.data.filename)
    icon_filename = secure_filename(form.icon.data.filename)
    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "updates"), exist_ok=True)
