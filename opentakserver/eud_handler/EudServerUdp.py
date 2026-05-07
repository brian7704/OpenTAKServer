import socket
import socketserver
import ssl


class EudServer(socketserver.ForkingUDPServer):
    allow_reuse_address = True
    daemon_threads = True
    logger = None
    port = 8087

    def __init__(self, server_address, eud_handler, logger, app_context):
        self.server_address = server_address
        self.logger = logger
        self.app_context = app_context
        super().__init__(server_address, eud_handler)

    def server_bind(self):
        super().server_bind()

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
