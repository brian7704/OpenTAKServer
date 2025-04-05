# Use an official Python slim image
FROM python:3.10-slim

# Set a non-root user and group
RUN addgroup --system appgroup && adduser --system --group --home /app appuser

# Set working directory
WORKDIR /app/opentakserver

# Copy the contents of the current directory (i.e. the opentakserver folder) to /app
COPY . /app/

# Set ownership of the /app directory to the non-root user
RUN chown -R appuser:appgroup /app

# Install required system packages (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a Python virtual environment
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Upgrade pip and install OpenTAKServer along with any requirements
RUN pip install --upgrade pip && pip install poetry

RUN poetry config virtualenvs.create false \
    && poetry lock \
    && poetry install --no-interaction --no-ansi

# Set the non-root user for running the container
USER appuser

# Expose the port the application listens on
EXPOSE 8081
EXPOSE 8089

# Start OpenTAKServer when the container runs
CMD ["/bin/sh", "-c", "DOCKER_WORKAROUND=true flask db upgrade && opentakserver"]