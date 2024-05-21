import typing as t

from flask_security import PasswordUtil


# Prevents @ and : characters in passwords. When using basic auth with RTSP streams these characters cause invalid URLs
class PasswordValidator(PasswordUtil):
    def validate(self, password: str, is_register: bool, **kwargs: t.Any) -> t.Tuple[t.Optional[t.List], str]:
        if '@' in password or ':' in password:
            return ["Passwords should not include @ or : characters"], password
        return super().validate(password, is_register, **kwargs)
