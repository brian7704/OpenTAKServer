# OpenTAKServer

![PyPI - Downloads](https://img.shields.io/pypi/dm/opentakserver)
![PyPI - Version](https://img.shields.io/pypi/v/opentakserver)
![Discord](https://img.shields.io/discord/1183578214459777164?logo=discord&label=Discord&link=https%3A%2F%2Fdiscord.gg%2F6uaVHjtfXN)
![GitHub Release Date](https://img.shields.io/github/release-date/brian7704/OpenTAKServer)


OpenTAKServer (OTS) is yet another open source TAK Server for ATAK, iTAK, and WinTAK. OTS's goal is to be easy to install and use, and to run on both servers and SBCs (ie Raspberry Pi).

Join us on our [Discord server](https://discord.gg/6uaVHjtfXN)

## Current Features
- Connect via TCP from ATAK, WinTAK, and iTAK
- SSL
- Authentication
- [WebUI with a live map](https://github.com/brian7704/OpenTAKServer-UI)
- Client certificate enrollment
- Send and receive messages
- Send and receive points
- Send and receive routes
- Send and receive images
- Share location with other users
- Save CoT messages to a database
- Data Packages
- Alerts
- CasEvac
- Optional Mumble server authentication
  - Use your OpenTAKServer username and password to log into your Mumble server
- Video Streaming
- Mission API
  - Data Sync plugin
  - Fire Area Survey plugin

## Planned Features
- Federation
- Groups/Channels

## Requirements
- RabbitMQ
- MediaMTX (Only required for video streaming)
- openssl
- nginx

## Installation

### Ubuntu

`curl https://i.opentakserver.io/ubuntu_installer -Ls | bash -`

### Raspberry Pi

`curl https://i.opentakserver.io/raspberry_pi_installer -Ls | bash -`

### Rocky 9

`curl -s -L https://i.opentakserver.io/rocky_linux_installer | bash -`

### Windows

Open PowerShell as an administrator and run the following command

`Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://i.opentakserver.io/windows_installer'))`

### MacOS

`curl -Ls https://i.opentakserver.io/macos_installer | bash -`

## Documentation

https://docs.opentakserver.io

## Supporting the project

If you would like to support the project you can do so [here](https://buymeacoffee.com/opentakserver)