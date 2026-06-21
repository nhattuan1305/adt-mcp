from uvicorn.config import LOGGING_CONFIG

from adt_mcp.__main__ import configure_logging


def test_configure_logging_adds_timestamps():
    configure_logging()
    fmts = LOGGING_CONFIG["formatters"]
    assert "%(asctime)s" in fmts["default"]["fmt"]
    assert "%(asctime)s" in fmts["access"]["fmt"]
    # access line still carries the request fields
    assert "%(request_line)s" in fmts["access"]["fmt"]
    assert "%(status_code)s" in fmts["access"]["fmt"]
