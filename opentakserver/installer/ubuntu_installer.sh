#!/bin/bash

. /etc/os-release

if [ "$NAME" != "Ubuntu" ]
then
  read -p "This installer is for Ubuntu but this system is $NAME. Do you want to run anyway? [y/N] " confirm && [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]] || exit 1
fi

sudo apt update && sudo apt upgrade -y
sudo apt install curl python3 python3-pip rabbitmq-server git openssl nginx openjdk-19-jre-headless -y
pip3 install poetry
git clone https://github.com/brian7704/OpenTAKServer.git /opt/OpenTAKServer
cd /opt/OpenTAKServer && poetry update && poetry install

echo "secret_key = '$(python3 -c 'import secrets; print(secrets.token_hex())')'" > /opt/OpenTAKServer/opentakserver/secret_key.py
echo "node_id = '$(python3 -c "import random; import string; print(''.join(random.choices(string.ascii_lowercase + string.digits, k=64)))")'" >> /opt/OpenTAKServer/opentakserver/secret_key.py
echo "security_password_salt = '$(python3 -c "import secrets; print(secrets.SystemRandom().getrandbits(128))")'" >> /opt/OpenTAKServer/opentakserver/secret_key.py
echo "server_address = 'example.com'" >> /opt/OpenTAKServer/opentakserver/secret_key.py # We'll fix this when OTS starts for the first time

echo "Setup is complete. You can start OpenTAKServer by running this command 'cd /opt/OpenTAKServer && poetry run python opentakserver/app.py"