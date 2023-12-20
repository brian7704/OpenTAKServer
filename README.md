# OpenTAKServer

OpenTAKServer (OTS) is yet another open source TAK Server for ATAK, iTAK, and WinTAK. OTS's goal is to be easy to install and use, and to run on both servers and SBCs (ie Raspberry Pi).

This project is just beginning and not yet suitable for production.

## Current Features
- Connect via TCP from ATAK
- SSL
- Send and receive messages
- Send and receive points
- Send and receive routes
- Share location with other users
- Save CoT messages to a database
- Data Packages
- Alerts
- CasEvac

## Planned Features
- WinTAK and iTAK support (This may already work, just needs to be tested)
- Authentication
- API to query saved CoT messages
- WebUI
  - Live Map
  - View saved CoT messages
  - Chat with EUDs
- Mission support
- Video Streaming
- Federation

## Requirements
- python = "^3.10"
- flask = "^3.0.0"
- bleach = "*"
- colorlog = "^6.7.0"
- flask-socketio = "^5.3.6"
- bs4 = "^0.0.1"
- datetime = "^5.3"
- gevent = "^23.9.1"
- ownca = "^0.4.0"
- pika = "^1.3.2"
- sqlalchemy = "^2.0.23"
- sqlalchemy-utils = "^0.41.1"
- flask-sqlalchemy = "^3.1.1"
- Flask-Security-Too = "^5.3.2"
- RabbitMQ
- MediaMTX (Only required for video streaming)

## Installation
```
apt install python3-pip rabbitmq-server git # Or substitude your distro's package manager
pip3 install poetry
git clone https://github.com/brian7704/OpenTAKServer.git
cd OpenTAKServer
poetry install
```

## Usage
```poetry run python opentakserver/app.py```