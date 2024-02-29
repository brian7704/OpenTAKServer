import os

import Ice

from flask_security import verify_password

# Load up Murmur slice file into Ice
Ice.loadSlice('', ['-I' + Ice.getSliceDir(), os.path.join(os.path.dirname(os.path.realpath(__file__)), 'Murmur.ice')])
import Murmur


class MumbleAuthenticator(Murmur.ServerUpdatingAuthenticator):
    texture_cache = {}

    def __init__(self, app, logger, ice):
        Murmur.ServerUpdatingAuthenticator.__init__(self)
        self.app = app
        self.logger = logger
        self.ice = ice

    def authenticate(self, username, password, certlist, certhash, strong, current=None):
        """
        This function is called to authenticate a user
        """
        if username == 'SuperUser':
            return (-2, None, None)

        self.logger.info("Mumble auth request for {}".format(username))

        with self.app.app_context():
            user = self.app.security.datastore.find_user(username=username)
            if not user:
                self.logger.warning("Mumble auth: User {} not found".format(username))
                return (-1, None, None)
            elif not user.active:
                self.logger.warning("Mumble auth: User {} is deactivated".format(username))
                return (-1, None, None)

            if verify_password(password, user.password):
                self.logger.info("Mumble auth: {} has been authenticated".format(username))
                return (user.id, user.username, None)

            self.logger.warning("Mumble auth: Bad password for {}".format(username))
            return (-1, None, None)

    def idToTexture(self, id, current=None):
        return

    def getInfo(self, id, current=None):
        """
        Gets called to fetch user specific information
        """

        # We do not expose any additional information so always fall through
        return (False, None)

    def nameToId(self, name, current=None):
        """
        Gets called to get the id for a given username
        """
        pass

    def idToName(self, id, current=None):
        """
        Gets called to get the username for a given id
        """
        pass

    def idToTexture(self, id, current=None):
        """
        Gets called to get the corresponding texture for a user
        """
        # seems like it pulled a user's avatar from a phpbb DB

    def registerUser(self, name, current=None):
        """
        Gets called when the server is asked to register a user.
        """
        pass

    def unregisterUser(self, id, current=None):
        """
        Gets called when the server is asked to unregister a user.
        """
        pass

    def getRegisteredUsers(self, filter, current=None):
        """
        Returns a list of usernames in the phpBB3 database which contain
        filter as a substring.
        """
        pass

    def setInfo(self, id, info, current=None):
        """
        Gets called when the server is supposed to save additional information
        about a user to his database
        """
        pass

    def setTexture(self, id, texture, current=None):
        """
        Gets called when the server is asked to update the user texture of a user
        """
        pass