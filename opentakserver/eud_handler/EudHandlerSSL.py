import traceback

from opentakserver.eud_handler.EudHandler import EudHandler


class EudHandlerSSL(EudHandler):

    timeout = 1.0
    shutdown = False
    common_name = None
    user = None
    is_ssl = True

    def setup(self):
        super().setup()

        try:
            self.request.do_handshake()
            for c in self.request.getpeercert()["subject"]:
                if c[0][0] == "commonName":
                    self.common_name = c[0][1]
                    self.logger.debug("Got common name {}".format(self.common_name))

                    with self.app.app_context():
                        self.user = self.app.security.datastore.find_user(username=self.common_name)
        except BaseException as e:
            self.logger.warning("Failed to do handshake: {}".format(e))
            self.logger.error(traceback.format_exc())
            self.close_connection()
