import socketserver
from threading import RLock


class EudServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    request_queue_size = 128
    logger = None
    port = 8088

    def __init__(self, server_address, eud_handler, logger, app_context):
        self.server_address = server_address
        self.logger = logger
        self.app_context = app_context
        self._identity_lock = RLock()
        self._identity_handlers = {}
        super().__init__(server_address, eud_handler)

    def claim_identity(self, handler, uid):
        """Make ``handler`` the sole live connection for an EUD identity.

        EUD queues are named by UID and callsign.  Allowing two consumers for
        the same identity makes RabbitMQ round-robin messages between the old
        and new sockets, and the older socket can later unbind the survivor's
        queues.  Keep the registry in the TCP server process so the newest
        connection can displace the old one before it starts consuming.
        """
        previous = None
        with self._identity_lock:
            previous = self._identity_handlers.get(uid)
            self._identity_handlers[uid] = handler

        if previous is not None and previous is not handler:
            self.logger.info(
                "Displacing older connection for %s from %s",
                uid,
                previous.client_address,
            )
            previous.displace()

    def release_identity(self, handler, uid):
        """Release an identity and report whether ``handler`` still owned it."""
        if not uid:
            return True

        with self._identity_lock:
            if self._identity_handlers.get(uid) is not handler:
                return False
            del self._identity_handlers[uid]
            return True

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
