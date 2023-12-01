import pika
from flask import Flask
import socket
import threading
# from flask_socketio import SocketIO

from client_handler import ClientHandler
from config import Config
from extensions import logger, db

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
            new_thread = ClientHandler(addr[0], addr[1], sock, lock, logger, app.app_context())
            new_thread.start()
            threads[addr[0]] = new_thread
        except KeyboardInterrupt:
            break


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    t = threading.Thread(target=launch_server)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', debug=True, use_reloader=False, port=Config.HTTP_PORT)
