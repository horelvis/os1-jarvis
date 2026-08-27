"""Shared fixtures for the plugin's tests.

Only one, and it exists because of a real defect: this plugin swallows
exceptions in two places on purpose (the dispatch loop must survive one
bad event, and an injection must not take the follower with it), and a
swallowed exception with no stack is invisible. The fixture is how
"keeps its traceback" becomes something a test can assert.
"""

import io

import pytest
from loguru import logger


@pytest.fixture
def capture_logs():
    """Everything loguru writes during one test, tracebacks included."""
    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG", backtrace=True, diagnose=False)
    try:
        yield sink
    finally:
        logger.remove(handler)
