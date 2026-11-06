import traceback

from cryptography import x509

from opentakserver.certificate_authority import is_revoked
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
            self.request.settimeout(10)
            self.request.do_handshake()
            self.request.settimeout(None)

            cert = x509.load_der_x509_certificate(self.request.getpeercert(binary_form=True))
            self.cert_serial = format(cert.serial_number, "x")
            if is_revoked(cert, self.app.config.get("OTS_CA_FOLDER")):
                self.logger.warning(
                    "Certificate {} is revoked, disconnecting {}".format(
                        self.cert_serial, self.client_address[0]
                    )
                )
                self.close_connection()
                return

            for c in self.request.getpeercert()["subject"]:
                if c[0][0] == "commonName":
                    self.common_name = c[0][1]
                    self.logger.debug("Got common name {}".format(self.common_name))

                    with self.app.app_context():
                        self.user = self.app.security.datastore.find_user(username=self.common_name)
                        self.handle_auth("")
        except BaseException as e:
            self.logger.warning("Failed to do handshake: {}".format(e))
            self.logger.error(traceback.format_exc())
            self.close_connection()
