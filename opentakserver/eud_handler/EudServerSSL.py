import os
import socket
import socketserver
import ssl

from opentakserver.eud_handler.EudServer import EudServer


class EudServerSSL(EudServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, eud_handler, logger, app_context):
        super().__init__(server_address, eud_handler, logger, app_context)

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        ssl_context.load_cert_chain(
            os.path.join(
                self.app_context.config.get("OTS_CA_FOLDER"),
                "certs",
                "opentakserver",
                "opentakserver.pem",
            ),
            os.path.join(
                self.app_context.config.get("OTS_CA_FOLDER"),
                "certs",
                "opentakserver",
                "opentakserver.nopass.key",
            ),
        )
        ssl_context.load_verify_locations(
            cafile=os.path.join(self.app_context.config.get("OTS_CA_FOLDER"), "ca.pem")
        )
        self.socket = ssl_context.wrap_socket(
            self.socket, server_side=True, do_handshake_on_connect=False
        )
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.logger.debug(f"listening on {self.server_address}")

    def server_activate(self):
        self.logger.debug("server activated")
        super().server_activate()

    def server_close(self):
        self.logger.debug("server closed")
        super().server_close()

    def process_request_thread(self, request, client_address):
        self.logger.debug("processing request thread")
        super().process_request_thread(request, client_address)

    def process_request(self, request, client_address):
        self.logger.debug("processing request")
        super().process_request(request, client_address)
