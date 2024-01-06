import os
import socket
import ssl
from threading import Thread

from controllers.client_controller import ClientController


class SocketServer(Thread):
    def __init__(self, logger, app, port=8088, ssl_server=False):
        super().__init__()

        self.logger = logger
        self.port = port
        self.ssl = ssl_server
        self.shutdown = False
        self.daemon = True
        self.socket = None
        self.clients = []
        self.app = app

    def run(self):
        if self.ssl:
            self.socket = self.launch_ssl_server()
        else:
            self.socket = self.launch_tcp_server()
        self.socket.settimeout(1.0)

        while not self.shutdown:
            try:
                sock, addr = self.socket.accept()
                if self.ssl:
                    self.logger.info("New SSL connection from {}".format(addr[0]))
                else:
                    self.logger.info("New TCP connection from {}".format(addr[0]))

                new_thread = ClientController(addr[0], addr[1], sock, self.logger)
                new_thread.daemon = True
                new_thread.start()
                self.clients.append(new_thread)
            except KeyboardInterrupt:
                break
            except TimeoutError:
                if self.shutdown:
                    self.socket.shutdown(socket.SHUT_RDWR)
                    self.socket.close()

        if self.ssl:
            self.logger.info("SSL server has shut down")
        else:
            self.logger.info("TCP server has shut down")

    def launch_tcp_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', self.port))
        s.listen(1)

        return s

    def launch_ssl_server(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            context = self.get_ssl_context()

            sconn = context.wrap_socket(sock, server_side=True)
            sconn.bind(('0.0.0.0', self.port))
            sconn.listen(0)

            return sconn

    def stop(self):
        if self.ssl:
            self.logger.warning("Shutting down SSL server")
        else:
            self.logger.warning("Shutting down TCP server")

        self.shutdown = True
        for client in self.clients:
            self.logger.debug('Attempting to stop client {}'.format(client.address))
            client.stop()

    def get_ssl_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

        self.logger.info("cert: {}".format(os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", self.app.config.get("OTS_SERVER_ADDRESS"),
                         self.app.config.get("OTS_SERVER_ADDRESS") + ".pem")))
        self.logger.info("key: {}".format(self.app.config.get("OTS_CA_FOLDER"), "certs", self.app.config.get("OTS_SERVER_ADDRESS"),
                         self.app.config.get("OTS_SERVER_ADDRESS") + ".nopass.key"))

        context.load_cert_chain(
            os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", self.app.config.get("OTS_SERVER_ADDRESS"),
                         self.app.config.get("OTS_SERVER_ADDRESS") + ".pem"),
            os.path.join(self.app.config.get("OTS_CA_FOLDER"), "certs", self.app.config.get("OTS_SERVER_ADDRESS"),
                         self.app.config.get("OTS_SERVER_ADDRESS") + ".nopass.key"))

        context.verify_mode = self.app.config.get("OTS_SSL_VERIFICATION_MODE")
        context.load_verify_locations(cafile=os.path.join(self.app.config.get("OTS_CA_FOLDER"), 'ca.pem'))

        return context