"""The bridge is a program, not a package: its modules import each other
by plain name (`import projects`), the way `server.py` runs them. So the
tests put its directory on the path rather than making it importable as
`Hermes.bridges...`, which would need __init__ files the runtime does
not want.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
