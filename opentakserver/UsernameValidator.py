import flask_security
import unicodedata
from flask_security import UsernameUtil
from opentakserver.extensions import logger


class UsernameValidator(UsernameUtil):

    def __init__(self, app):
        super().__init__(app)
        self.app = app

    def check_username(self, username: str) -> str | None:
        """
        Allow letters, numbers, underscores and periods in usernames
        """
        for character in username:
            if unicodedata.category(character)[0] not in ["L", "N"] and character != "_" and character != ".":
                return flask_security.utils.get_message("USERNAME_DISALLOWED_CHARACTERS")[0]
        return None
