# Generate a key using `python3 -c 'import secrets; print(secrets.token_hex())'` and rename this file secret_key.py
import os

secret_key = 'changeme'
node_id = 'changeme'  # Generate using ''.join(random.choices(string.ascii_lowercase + string.digits, k=64))
security_password_salt = os.environ.get("SECURITY_PASSWORD_SALT", 'changeme')  # secrets.SystemRandom().getrandbits(128)
server_domain_or_ip = "example.com"
