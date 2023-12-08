# Generate a key using `python3 -c 'import secrets; print(secrets.token_hex())'` and rename this file secret_key.py

secret_key = 'changeme'
node_id = 'changeme'  # Generate using ''.join(random.choices(string.ascii_lowercase + string.digits, k=64))
