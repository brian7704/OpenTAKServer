import os

import Ice
from flask import Flask
from flask_ldap3_login import AuthenticationResponseStatus
from flask_security import verify_password

from ..extensions import ldap_manager

# Load up Murmur slice file into Ice
Ice.loadSlice(
    "",
    [
        "-I" + Ice.getSliceDir(),
        os.path.join(os.path.dirname(os.path.realpath(__file__)), "Murmur.ice"),
    ],
)
import Murmur


class MumbleAuthenticator(Murmur.ServerUpdatingAuthenticator):
    texture_cache = {}

    def __init__(self, app, logger, ice):
        Murmur.ServerUpdatingAuthenticator.__init__(self)
        self.app: Flask = app
        self.logger = logger
        self.ice = ice

    def authenticate(self, username, password, certlist, certhash, strong, current=None):
        """
        This function is called to authenticate a user
        Returns: (userid, username, groups) tuple
        - userid: unique Mumble user ID
        - username: display name in Mumble
        - groups: list of Mumble groups the user should be added to
        """
        if username == "SuperUser":
            return (-2, None, None)

        self.logger.info("Mumble auth request for {}".format(username))

        with self.app.app_context():
            # Try to find user by username first
            user = self.app.security.datastore.find_user(username=username)
            is_callsign_auth = False
            callsign_username = username
            
            # If not found by username, try by callsign (for ATAK clients)
            if not user:
                from opentakserver.models.EUD import EUD
                
                # Try exact callsign match first
                eud = EUD.query.filter_by(callsign=username).first()
                
                # If not found and username contains "---", strip UUID suffix (ATAK appends ---<uuid>)
                if not eud and "---" in username:
                    base_callsign = username.split("---")[0]
                    self.logger.info("Mumble auth: Trying base callsign: {}".format(base_callsign))
                    eud = EUD.query.filter_by(callsign=base_callsign).first()
                
                if eud and eud.user_id:
                    user = self.app.security.datastore.find_user(id=eud.user_id)
                    if user:
                        is_callsign_auth = True
                        self.logger.info("Mumble auth: Matched callsign {} to user {}".format(username, user.username))
            
            if not user:
                self.logger.warning("Mumble auth: User {} not found".format(username))
                return -1, None, None
            elif not user.active:
                self.logger.warning("Mumble auth: User {} is deactivated".format(username))
                return -1, None, None

            # Get user's OTS groups for Mumble group membership
            mumble_groups = []
            for group in user.groups:
                mumble_groups.append(group.name)
                self.logger.info("Mumble auth: Adding user {} to group {}".format(username, group.name))
            
            # Check if user is administrator (username 'administrator' or has all 6 groups)
            if user.username == 'administrator' or len(user.groups) >= 6:
                mumble_groups.append('admin')
                self.logger.info("Mumble auth: User {} is admin".format(username))

            if self.app.config.get("OTS_ENABLE_LDAP"):
                auth_result = ldap_manager.authenticate(username, password)
                if auth_result.status == AuthenticationResponseStatus.success:
                    self.logger.info("Mumble auth: {} has been authenticated".format(username))

                    # Keep this import here to avoid a circular import when OTS is started
                    from opentakserver.blueprints.ots_api.ldap_api import save_user

                    save_user(
                        auth_result.user_dn,
                        auth_result.user_id,
                        auth_result.user_info,
                        auth_result.user_groups,
                    )

                    # Generate unique Mumble user ID and display name
                    if is_callsign_auth:
                        import hashlib
                        hash_offset = int(hashlib.md5(callsign_username.encode()).hexdigest(), 16) % 999 + 1
                        mumble_user_id = user.id * 1000 + hash_offset
                        mumble_display_name = callsign_username
                        self.logger.info("Mumble auth: Assigned unique ID {} and name {} for callsign with groups: {}".format(mumble_user_id, mumble_display_name, mumble_groups))
                    else:
                        mumble_user_id = user.id * 1000
                        mumble_display_name = user.username
                        self.logger.info("Mumble auth: Assigned ID {} for username {} with groups: {}".format(mumble_user_id, mumble_display_name, mumble_groups))
                    
                    return mumble_user_id, mumble_display_name, mumble_groups

            elif verify_password(password, user.password):
                self.logger.info("Mumble auth: {} has been authenticated".format(username))
                
                # Generate unique Mumble user ID and display name to allow same OTS user on multiple devices
                # Username-based auth (PC): use base ID * 1000, show OTS username
                # Callsign-based auth (ATAK): use base ID * 1000 + hash offset, show callsign
                if is_callsign_auth:
                    # Create unique ID for each device using hash of full callsign
                    import hashlib
                    hash_offset = int(hashlib.md5(callsign_username.encode()).hexdigest(), 16) % 999 + 1
                    mumble_user_id = user.id * 1000 + hash_offset
                    mumble_display_name = callsign_username  # Show device callsign in Mumble
                    self.logger.info("Mumble auth: Assigned unique ID {} and name {} for callsign with groups: {}".format(mumble_user_id, mumble_display_name, mumble_groups))
                else:
                    # Direct username authentication
                    mumble_user_id = user.id * 1000
                    mumble_display_name = user.username  # Show OTS username in Mumble
                    self.logger.info("Mumble auth: Assigned ID {} for username {} with groups: {}".format(mumble_user_id, mumble_display_name, mumble_groups))
                    
                return mumble_user_id, mumble_display_name, mumble_groups

            self.logger.warning("Mumble auth: Bad password for {}".format(username))
            return -1, None, None

    def idToTexture(self, id, current=None):
        return

    def getInfo(self, id, current=None):
        """
        Gets called to fetch user specific information
        """

        # We do not expose any additional information so always fall through
        return False, None

    def nameToId(self, name, current=None):
        """
        Gets called to get the id for a given username
        """
        return -2

    def idToName(self, id, current=None):
        """
        Gets called to get the username for a given id
        """
        return None

    def idToTexture(self, id, current=None):
        """
        Gets called to get the corresponding texture for a user
        """
        # seems like it pulled a user's avatar from a phpbb DB

    def registerUser(self, name, current=None):
        """
        Gets called when the server is asked to register a user.
        """
        return -2

    def unregisterUser(self, id, current=None):
        """
        Gets called when the server is asked to unregister a user.
        """
        return -1

    def getRegisteredUsers(self, filter, current=None):
        """
        Returns a list of usernames in the phpBB3 database which contain
        filter as a substring.
        """
        return []

    def getRegistration(self, id, current=None):
        """
        Gets called to fetch user registration info including group memberships.
        Returns UserInfoMap with user details.
        """
        self.logger.info("Mumble getRegistration called for ID {}".format(id))
        
        with self.app.app_context():
            # Decode Mumble ID back to OTS user ID (base ID is ID // 1000)
            ots_user_id = id // 1000
            
            from opentakserver.models.User import User
            from opentakserver.models.Group import Group
            
            user = User.query.get(ots_user_id)
            if not user:
                self.logger.warning("Mumble getRegistration: User ID {} not found".format(ots_user_id))
                # Return empty dict to indicate user not found
                return {}
            
            # Build user info map
            user_info = {}
            user_info[Murmur.UserInfo.UserName] = user.username
            
            if user.email:
                user_info[Murmur.UserInfo.UserEmail] = user.email
            
            # Get user's OTS groups and map to Mumble groups
            # Each OTS group becomes a Mumble group on the corresponding channel
            groups = user.groups
            group_names = []
            
            for group in groups:
                # Add group name (this will be used for Mumble group membership)
                group_names.append(group.name)
                self.logger.info("Mumble getRegistration: User {} is in group {}".format(user.username, group.name))
            
            # Check if user is administrator (has all groups or specific admin flag)
            # For now, check if user has username 'administrator' or is in all groups
            if user.username == 'administrator' or len(groups) >= 6:  # All 6 groups
                group_names.append('admin')
                self.logger.info("Mumble getRegistration: User {} is admin".format(user.username))
            
            self.logger.info("Mumble getRegistration: User {} groups: {}".format(user.username, group_names))
            
            return user_info

    def setInfo(self, id, info, current=None):
        """
        Gets called when the server is supposed to save additional information
        about a user to his database
        """
        return 0

    def setTexture(self, id, texture, current=None):
        """
        Gets called when the server is asked to update the user texture of a user
        """
        return -1
        pass
