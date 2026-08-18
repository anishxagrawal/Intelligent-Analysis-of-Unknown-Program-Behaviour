"""AC-S6: the logger emits parseable JSON including a request id."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from app.logging import JsonFormatter, configure_logging, get_logger, set_request_id

pytestmark = pytest.mark.unit


def _capture(logger_name: str = "test.logger") -> tuple[logging.Logger, StringIO]:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, stream


def test_output_is_valid_json() -> None:
    logger, stream = _capture()
    logger.info("hello")

    record = json.loads(stream.getvalue())
    assert record["message"] == "hello"
    assert record["level"] == "INFO"
    assert record["logger"] == "test.logger"
    assert "timestamp" in record


def test_request_id_is_included() -> None:
    logger, stream = _capture()
    set_request_id("abc-123")
    try:
        logger.info("with correlation")
    finally:
        set_request_id(None)

    assert json.loads(stream.getvalue())["request_id"] == "abc-123"


def test_request_id_is_null_when_unset() -> None:
    logger, stream = _capture()
    set_request_id(None)
    logger.info("no correlation")

    assert json.loads(stream.getvalue())["request_id"] is None


def test_extra_fields_are_forwarded() -> None:
    logger, stream = _capture()
    logger.info("submission", extra={"job_id": "job-1", "size_bytes": 42})

    record = json.loads(stream.getvalue())
    assert record["job_id"] == "job-1"
    assert record["size_bytes"] == 42


def test_exceptions_are_captured() -> None:
    logger, stream = _capture()
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("it failed")

    record = json.loads(stream.getvalue())
    assert "ValueError: boom" in record["exception"]


def test_configure_logging_replaces_handlers_rather_than_accumulating() -> None:
    configure_logging("DEBUG")
    first = len(logging.getLogger().handlers)
    configure_logging("DEBUG")

    assert len(logging.getLogger().handlers) == first == 1
    assert logging.getLogger().level == logging.DEBUG


def test_get_logger_returns_named_logger() -> None:
    assert get_logger("app.thing").name == "app.thing"
