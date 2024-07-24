import os
import threading
from threading import Timer

import Ice

from opentakserver.mumble.mumble_authenticator import MumbleAuthenticator

# Load up Murmur slice file into Ice
Ice.loadSlice('', ['-I' + Ice.getSliceDir(), os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Murmur.ice')])
import Murmur


class MumbleIceDaemon(threading.Thread):
    def __init__(self, app, logger):
        super().__init__()
        self.app = app
        self.logger = logger
        self.logger.info("mumble daemon init")
        self.daemon = True

    def run(self):
        # Configure Ice properties
        props = Ice.createProperties()
        props.setProperty("Ice.ImplicitContext", "Shared")
        props.setProperty('Ice.Default.EncodingVersion', '1.0')
        props.setProperty('Ice.Default.InvocationTimeout', str(30 * 1000))
        props.setProperty('Ice.MessageSizeMax', str(1024))
        idata = Ice.InitializationData()
        idata.properties = props

        # Create Ice connection
        ice = Ice.initialize(idata)
        proxy = ice.stringToProxy('Meta:tcp -h 127.0.0.1 -p 6502')
        secret = ''
        if secret != '':
            ice.getImplicitContext().put("secret", secret)
        try:
            meta = Murmur.MetaPrx.checkedCast(proxy)
        except Ice.ConnectionRefusedException:
            self.logger.error("Failed to connect to the mumble ice server")
            return

        mumble_ice_app = MumbleIceApp(self.app, self.logger, ice)
        mumble_ice_app.run()


class MumbleIceApp(Ice.Application):
    def __init__(self, app, logger, ice):
        super().__init__()
        self.app = app
        self.logger = logger
        self.ice = ice
        self.meta = None
        self.metacb = None
        self.connected = False
        self.failed_watch = False
        self.watchdog = None
        self.auth = None

    def run(self, *args):
        if not self.initialize_ice_connection():
            self.logger.error("Mumble server connection failed")
            return 1

        self.check_connection()

        self.watchdog.cancel()

        if self.interrupted():
            self.logger.warning('Caught interrupt, shutting down')

        return 0

    def initialize_ice_connection(self):
        """
        Establishes the two-way Ice connection and adds the authenticator to the
        configured servers
        """

        # if False and 'ice_secret':
        #     self.ice.getImplicitContext().put("secret", "some_secret")

        self.logger.debug('Connecting to Ice server ({}:{})'.format('127.0.0.1', 6502))
        base = self.ice.stringToProxy('Meta:tcp -h {} -p {}'.format('127.0.0.1', 6502))
        self.meta = Murmur.MetaPrx.uncheckedCast(base)

        adapter = self.ice.createObjectAdapterWithEndpoints('Callback.Client', 'tcp -h 127.0.0.1')
        adapter.activate()

        metacbprx = adapter.addWithUUID(MetaCallback(self))
        self.metacb = Murmur.MetaCallbackPrx.uncheckedCast(metacbprx)

        authprx = adapter.addWithUUID(MumbleAuthenticator(self.app, self.logger, self.ice))
        self.auth = Murmur.ServerUpdatingAuthenticatorPrx.uncheckedCast(authprx)

        return self.attach_callbacks()

    def attach_callbacks(self):
        """
        Attaches all callbacks for meta and authenticators
        """

        try:
            self.logger.debug('Attaching meta callback')

            self.meta.addCallback(self.metacb)

            for server in self.meta.getBootedServers():
                self.logger.debug('Setting mumble authenticator for virtual server {}'.format(server.id()))
                server.setAuthenticator(self.auth)

        except (Murmur.InvalidSecretException, Ice.UnknownUserException, Ice.ConnectionRefusedException) as e:
            if isinstance(e, Ice.ConnectionRefusedException):
                self.logger.warning('Server refused connection')
            elif isinstance(e, Murmur.InvalidSecretException) or \
                    isinstance(e, Ice.UnknownUserException) and (e.unknown == 'Murmur::InvalidSecretException'):
                self.logger.error('Invalid ice secret')
            else:
                # We do not actually want to handle this one, re-raise it
                raise e

            self.connected = False
            return False

        self.connected = True
        return True

    def check_connection(self):
        """
        Tries reapplies all callbacks to make sure the authenticator
        survives server restarts and disconnects.
        """

        try:
            self.attach_callbacks()
        except Ice.Exception as e:
            self.logger.warning('{}: Failed connection check, will retry in next watchdog run ({}s)'.format(e, 10))

        # Renew the timer
        self.watchdog = Timer(10, self.check_connection)
        self.watchdog.start()


class MetaCallback(Murmur.MetaCallback):
    def __init__(self, authenticator):
        Murmur.MetaCallback.__init__(self)
        self.authenticator = authenticator

    def started(self, server, current=None):
        """
        This function is called when a virtual server is started
        and makes sure an authenticator gets attached if needed.
        """
        self.authenticator.logger.info('Setting authenticator for virtual server {}'.format(server.id()))
        try:
            server.setAuthenticator(self.authenticator.auth)
        # Apparently this server was restarted without us noticing
        except (Murmur.InvalidSecretException, Ice.UnknownUserException) as e:
            if hasattr(e, "unknown") and e.unknown != "Murmur::InvalidSecretException":
                # Special handling for Murmur 1.2.2 servers with invalid slice files
                raise e

            return

    def stopped(self, server, current=None):
        """
        This function is called when a virtual server is stopped
        """
        if self.authenticator.connected:
            # Only try to output the server id if we think we are still connected to prevent
            # flooding of our thread pool
            try:
                self.authenticator.logger.info('Authenticated virtual server {} got stopped'.format(server.id()))
                return
            except Ice.ConnectionRefusedException:
                self.authenticator.connected = False

        self.authenticator.logger.info('Server shutdown stopped a virtual server')
