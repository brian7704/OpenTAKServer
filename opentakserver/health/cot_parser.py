import os
import re
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

COT_PARSER_SERVICE = os.getenv("COT_PARSER_SERVICE", "cot-parser.service")
OTS_DATA_FOLDER = os.getenv("OTS_DATA_FOLDER", os.path.join(Path.home(), "ots"))
COT_PARSER_LOG = os.getenv(
    "COT_PARSER_LOG",
    os.path.join(OTS_DATA_FOLDER, "logs", "opentakserver.log"),
)
RABBIT_HOST = os.getenv("RABBIT_HOST", "localhost")
RABBIT_PORT = int(os.getenv("RABBIT_PORT", "5672"))
ERROR_PATTERN = os.getenv("COT_PARSER_ERROR_REGEX", r"(ERROR|Exception|Traceback)")
ERROR_REGEX = re.compile(ERROR_PATTERN, re.IGNORECASE)
LOG_TAG = "cot_parser"


def query_systemd(service: str = COT_PARSER_SERVICE) -> str:
    """Return the ActiveState for a systemd service.

    If systemctl is unavailable or an error occurs, a description of the
    error is returned instead of raising an exception.
    """
    try:
        completed = subprocess.run(
            [
                "systemctl",
                "show",
                service,
                "--property=ActiveState",
                "--value",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()
    except Exception as exc:  # pragma: no cover - exercised via tests
        return f"error: {exc}"  # noqa: TRY002


def tail_ots_log_for_cot_parser_entries(
    path: str = COT_PARSER_LOG, lines: int = 100, tag: str = LOG_TAG
) -> List[str]:
    """Return the last ``lines`` from the OTS log produced by ``cot_parser``."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = 1024
            data = bytearray()
            while size > 0 and data.count(b"\n") <= lines:
                step = min(block, size)
                size -= step
                fh.seek(size)
                data = fh.read(step) + data
            log_lines = data.decode(errors="ignore").splitlines()
            return [line for line in log_lines if tag in line][-lines:]
    except OSError as exc:  # pragma: no cover - exercised via tests
        return [f"error: {exc}"]


def find_errors(lines: Iterable[str]) -> List[str]:
    """Filter log lines that match ``ERROR_REGEX``."""
    return [line for line in lines if ERROR_REGEX.search(line)]


def rabbitmq_check(host: str = RABBIT_HOST, port: int = RABBIT_PORT, timeout: float = 1.0) -> bool:
    """Attempt a TCP connection to RabbitMQ and return whether it succeeded."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:  # pragma: no cover - exercised via tests
        return False


def compute_status(service_state: str, log_errors: List[str], rabbitmq_ok: bool) -> dict:
    """Compute component and overall health status."""
    components = {
        "service": service_state,
        "logs": "errors" if log_errors else "ok",
        "rabbitmq": "up" if rabbitmq_ok else "down",
    }
    problems: List[str] = []
    if service_state != "active":
        problems.append("cot-parser service inactive")
    if log_errors:
        problems.append("errors detected in log")
    if not rabbitmq_ok:
        problems.append("rabbitmq unreachable")

    overall = "healthy" if not problems else "unhealthy"
    return {
        "overall": overall,
        "components": components,
        "problems": problems,
    }


def current_timestamp() -> str:
    """Return an ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()

