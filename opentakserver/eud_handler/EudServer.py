import socket
import socketserver
import ssl


class EudServer(socketserver.ForkingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    logger = None
    port = 8088

    def __init__(self, server_address, eud_handler, logger):
        super().__init__(server_address, eud_handler)
        self.server_address = server_address
        self.logger = logger

    def server_bind(self):
        super().server_bind()

    def server_activate(self):
        print("server activated")
        super().server_activate()

    def server_close(self):
        print("server closed")
        super().server_close()

    def process_request_thread(self, request, client_address):
        print("processing request thread")
        super().process_request_thread(request, client_address)

    def process_request(self, request, client_address):
        print("processing request")
        super().process_request(request, client_address)
