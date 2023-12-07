import os

import pika
from flask import Flask, request, send_from_directory
import socket
import threading

from werkzeug.utils import secure_filename

# from flask_socketio import SocketIO

from opentakserver.controllers.client_controller import ClientController
from config import Config
from extensions import logger, db
from opentakserver.controllers.cot_controller import CoTController
from opentakserver.models.DataPackage import DataPackage

app = Flask(__name__)
app.config.from_object(Config)
# socketio = SocketIO(app)
clients = {}

db.init_app(app)

rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = rabbit_connection.channel()
channel.exchange_declare('cot', durable=True, exchange_type='fanout')
channel.exchange_declare('dms', durable=True, exchange_type='direct')
channel.exchange_declare('chatrooms', durable=True, exchange_type='direct')


@app.route('/Marti/api/clientEndPoints')
def client_end_points():
    logger.debug("endpoints")
    return {"data": [{"callsign": "DOWN", "lastEventTime": "2023-06-16T15:20:55.871Z", "lastStatus": "Connected",
                      "uid": "ANDROID-199eeda473669973", "username": "ghost"}],
            "nodeId": "jhtsjls2925a1e2ldaclrwjec2d2pa8w", "type": "com.bbn.marti.remote.ClientEndpoint", "version": "3"}


@app.route('/Marti/api/version/config')
def marti_config():
    logger.debug('marti_config')
    return {"version": "3", "type": "ServerConfig",
            "data": {"version": Config.VERSION, "api": "3", "hostname": "0.0.0.0"},
            "nodeId": "jhtsjls2925a1e2ldaclrwjec2d2pa8w"}


@app.route('/Marti/sync/missionupload', methods=['POST'])
def data_package_share():
    if not len(request.files):
        logger.error(('no file: {} --- {}'.format(request.files, len(request.files))))
        return {'error': 'no file'}, 400, {'Content-Type': 'application/json'}
    for file in request.files:
        logger.debug(request.files[file])
        file = request.files['assetfile']
        if file:
            if file.content_type != 'application/x-zip-compressed':
                return {'error': 'Please only upload zip files'}, 400, {'Content-Type': 'application/json'}
            filename = secure_filename(request.args.get('hash') + '.zip')
            logger.debug(filename)
            file.save(os.path.join(Config.UPLOAD_FOLDER, filename))

            data_package = DataPackage()
            data_package.filename = filename
            data_package.hash = request.args.get('hash')
            data_package.creatorUid = request.args.get('creatorUid')
            db.session.add(data_package)
            db.session.commit()

            return ('http://{}/Marti/api/sync/metadata/{}/tool'.format(
                request.headers.get('Host'), request.args.get('hash')), 200,
                    {'Content-Type': 'application/json'})


@app.route('/Marti/api/sync/metadata/<file_hash>/tool', methods=['GET', 'PUT'])
def data_package_metadata(file_hash):
    if request.method == 'PUT':
        return "Okay", 200
    elif request.method == 'GET':
        data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()
        return send_from_directory(Config.UPLOAD_FOLDER, data_package.hash + ".zip", download_name=data_package.filename)


def launch_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', Config.COT_STREAMING_PORT))
    s.listen(1)

    threads = {}
    lock = threading.Lock()

    while True:
        try:
            s.listen(1)
            sock, addr = s.accept()
            logger.info("New connection from {}".format(addr[0]))
            new_thread = ClientController(addr[0], addr[1], sock, lock, logger, app.app_context())
            new_thread.daemon = True
            new_thread.start()
            threads[addr[0]] = new_thread
        except KeyboardInterrupt:
            break


if __name__ == '__main__':
    with app.app_context():
        logger.debug("Creating DB")
        db.create_all()
    t = threading.Thread(target=launch_server)
    t.daemon = True
    t.start()
    # t.join()

    cot_thread = CoTController(app.app_context(), logger, db)
    cot_thread.daemon = True
    cot_thread.start()
    # cot_thread.join()

    app.run(host='0.0.0.0', debug=True, use_reloader=False, port=Config.HTTP_PORT)
