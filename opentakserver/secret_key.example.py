"""
These values will be automatically generated the first time OpenTAKServer is run. If you would like to change
them manually, rename this file secret_key.py and set OTS_FIRST_RUN to False in config.py
"""
secret_key = 'changeme'  # `python3 -c 'import secrets; print(secrets.token_hex())'`
node_id = 'changeme'  # ''.join(random.choices(string.ascii_lowercase + string.digits, k=64))
security_password_salt = 'changeme'  # secrets.SystemRandom().getrandbits(128)
server_address = "example.com"
