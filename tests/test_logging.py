import io
import logging

from opentakserver.extensions import logger


def test_opentakserver_logger_does_not_propagate_to_root(monkeypatch):
    root_logger = logging.getLogger()
    named_output = io.StringIO()
    root_output = io.StringIO()

    monkeypatch.setattr(logger, "handlers", [logging.StreamHandler(named_output)])
    monkeypatch.setattr(root_logger, "handlers", [logging.StreamHandler(root_output)])
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "level", logging.DEBUG)

    logger.debug("logging-regression-sentinel")

    assert logger.propagate is False
    assert named_output.getvalue() == "logging-regression-sentinel\n"
    assert root_output.getvalue() == ""
