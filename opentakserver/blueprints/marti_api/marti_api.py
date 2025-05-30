import glob
import os
import traceback
from urllib.parse import urlparse, unquote

from OpenSSL import crypto
from flask import request, Blueprint, current_app as app, jsonify, send_from_directory
from flask_security import current_user
from simplekml import Kml, GxTrack, IconStyle, Icon, Style, GxMultiTrack, Document

from opentakserver.extensions import logger, db
from opentakserver.functions import iso8601_string_from_datetime, datetime_from_iso8601_string
from opentakserver import __version__ as version
from opentakserver.models.EUD import EUD
from opentakserver.models.Point import Point

marti_api = Blueprint('marti_api', __name__)


# Verifies the client cert forwarded by nginx in the X-Ssl-Cert header
# Returns the parsed cert if valid, otherwise returns False
def verify_client_cert():
    cert_header = app.config.get("OTS_SSL_CERT_HEADER")
    if cert_header not in request.headers:
        return False

    cert = unquote(request.headers.get(cert_header))
    cert = crypto.load_certificate(crypto.FILETYPE_PEM, cert)
    with open(os.path.join(app.config.get("OTS_CA_FOLDER"), "ca.pem"), 'rb') as f:
        ca_cert = crypto.load_certificate(crypto.FILETYPE_PEM, f.read())

    store = crypto.X509Store()
    store.add_cert(ca_cert)
    ctx = crypto.X509StoreContext(store, cert)

    try:
        ctx.verify_certificate()
        return cert
    except crypto.X509StoreContextError:
        return False


@marti_api.route('/Marti/api/clientEndPoints', methods=['GET'])
def client_end_points():
    # TODO: Add group support ?group=__ANON__
    euds = db.session.execute(db.select(EUD)).scalars()
    return_value = {'version': 3, "type": "com.bbn.marti.remote.ClientEndpoint", 'data': [],
                    'nodeId': app.config.get("OTS_NODE_ID")}
    for eud in euds:
        if not eud.callsign:
            continue

        return_value['data'].append({
            'callsign': eud.callsign,
            'uid': eud.uid,
            'username': current_user.username if current_user.is_authenticated else 'anonymous',
            'lastEventTime': iso8601_string_from_datetime(eud.last_event_time),
            'lastStatus': eud.last_status
        })

    return return_value, 200, {'Content-Type': 'application/json'}


@marti_api.route('/Marti/api/version/config', methods=['GET'])
def marti_config():
    url = urlparse(request.url_root)

    return {"version": "3", "type": "ServerConfig",
            "data": {"version": version, "api": "3", "hostname": url.hostname},
            "nodeId": app.config.get("OTS_NODE_ID")}, 200, {'Content-Type': 'application/json'}


@marti_api.route('/Marti/ExportMissionKML')
def atak_track_history():
    try:
        start_time = request.args.get('startTime')
        end_time = request.args.get('endTime')
        uid = request.args.get('uid')
        file_format = request.args.get('format')
        # Not sure what these three are supposed to do
        multitrack_threshold = request.args.get('multiTrackThreshold')
        extended_data = request.args.get('extendedData')
        optimize_export = request.args.get('optimizeExport')

        kml = Kml()
        doc: Document = kml.newdocument(name=uid)

        eud = db.session.execute(db.session.query(EUD).filter_by(uid=uid)).first()
        if not eud:
            return jsonify({'success': False, 'error': f"No such UID: {uid}"}), 400
        eud: EUD = eud[0]

        icon = Icon(href=f"files/team_{eud.team.name.lower().replace(' ', '')}.png")
        icon_style = IconStyle(scale=1.0, heading=0.0, icon=icon)
        style = Style(iconstyle=icon_style)
        doc.styles.append(style)
        kml.addfile(os.path.join(os.path.dirname(os.path.realpath(__file__)), "icons", f"team_{eud.team.name.lower().replace(' ', '')}.png"))

        query = db.session.query(Point)

        if uid:
            query = query.filter(Point.device_uid == uid)

        if start_time:
            query = query.filter(Point.timestamp >= datetime_from_iso8601_string(start_time))

        if end_time:
            query = query.filter(Point.timestamp <= datetime_from_iso8601_string(end_time))

        points = db.session.execute(query)
        timestamps = []
        coords = []
        for point in points:
            point = point[0]
            timestamps.append(iso8601_string_from_datetime(point.timestamp))
            coords.append((point.longitude, point.latitude))

        multitrack: GxMultiTrack = doc.newgxmultitrack(gxinterpolate=0)
        multitrack.style = style
        multitrack.name = eud.callsign

        track: GxTrack = multitrack.newgxtrack(name=uid, gxaltitudemode="clampToGround")
        track.newwhen(timestamps)
        track.newgxcoord(coords)

        if file_format == "kmz":
            kml.savekmz(os.path.join(app.config.get("UPLOAD_FOLDER"), f"{uid}.kmz"))
            return send_from_directory(app.config.get("UPLOAD_FOLDER"), f"{uid}.kmz", as_attachment=True, download_name=f"{uid}.kmz")
        else:
            kml.save(os.path.join(app.config.get("UPLOAD_FOLDER"), f"{uid}.kml"))
            return send_from_directory(app.config.get("UPLOAD_FOLDER"), f"{uid}.kml", as_attachment=True, download_name=f"{uid}.kml")

    except BaseException as e:
        logger.error(f"Failed to generate KML: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500
