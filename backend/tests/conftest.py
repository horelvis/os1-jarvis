"""Pytest setup for the Samantha backend tests.

`samantha.config` reads env vars at import time. To keep the integration
tests (TestClient against the FastAPI app) from creating ChromaDB files
under the developer's home directory, we disable persistent memory for
the default integration suite. Dedicated `Memory` unit tests construct
their own instance against pytest's `tmp_path` fixture and bypass this.
"""

import os

# Must run before `from samantha.api import app` happens anywhere.
os.environ.setdefault("SAMANTHA_MEMORY_ENABLED", "false")
