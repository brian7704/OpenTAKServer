import json
import os
import traceback
from urllib.parse import urlparse, unquote

from xml.etree.ElementTree import Element, tostring, fromstring

import bleach
import sqlalchemy
from OpenSSL import crypto
from bs4 import BeautifulSoup
from flask import request, Blueprint, jsonify, current_app as app
from flask_security import current_user

from opentakserver.extensions import logger, db
from opentakserver.forms.MediaMTXPathConfig import MediaMTXPathConfig
from opentakserver.functions import iso8601_string_from_datetime
from opentakserver import __version__ as version
from opentakserver.models.EUD import EUD
from opentakserver.models.VideoStream import VideoStream

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
