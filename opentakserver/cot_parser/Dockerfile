FROM python:3.13

RUN addgroup --system ots && adduser --system --group --home /app ots

WORKDIR /app/opentakserver

COPY . /app/

RUN chown -R appuser:appgroup /app

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

RUN pip install opentakserver

USER ots

ENTRYPOINT ["eud_handler"]

# Flask will stop gracefully on SIGINT (Ctrl-C).
# Docker compose tries to stop processes using SIGTERM by default, then sends SIGKILL after a delay if the process doesn't stop.
STOPSIGNAL SIGINT