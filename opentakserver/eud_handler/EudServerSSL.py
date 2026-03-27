import socket
import socketserver
import ssl

from opentakserver.eud_handler.EudServer import EudServer


class EudServerSSL(EudServer):
    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self):
        # self.socket.setsockopt(socket.AF_INET, socket.SOCK_STREAM, 0)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        ssl_context.load_cert_chain(
            "/home/administrator/ots/ca/certs/opentakserver/opentakserver.pem",
            "/home/administrator/ots/ca/certs/opentakserver/opentakserver.nopass.key",
        )
        ssl_context.load_verify_locations("/home/administrator/ots/ca/ca.pem")
        self.socket = ssl_context.wrap_socket(self.socket, server_side=True)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        print(f"listening on {self.server_address}")

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
