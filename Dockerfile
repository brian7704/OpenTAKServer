FROM python:3.13

RUN addgroup --gid 1024 ots
RUN adduser --home /app --disabled-password --gecos "" --force-badname --gid 1024 ots

USER ots

WORKDIR /app/opentakserver

RUN chown -R ots:ots /app

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

RUN pip install opentakserver

USER ots

EXPOSE 8081

ENTRYPOINT ["opentakserver"]

# Flask will stop gracefully on SIGINT (Ctrl-C).
# Docker compose tries to stop processes using SIGTERM by default, then sends SIGKILL after a delay if the process doesn't stop.
STOPSIGNAL SIGINT

HEALTHCHECK --interval=1m CMD curl --fail http://localhost:8081/api/health || exit 1