"""Architecture tests (P0-T05, section 3A).

The cache/queue abstraction is only worth having if nothing bypasses it, so
these tests fail the build when application code imports a client directly.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

REDIS_IMPORT = re.compile(r"^\s*(?:import\s+redis|from\s+redis(?:\.\w+)*\s+import)", re.MULTILINE)
ARQ_IMPORT = re.compile(r"^\s*(?:import\s+arq|from\s+arq(?:\.\w+)*\s+import)", re.MULTILINE)

# The single allowed boundary for each client library.
ALLOWED = {
    "redis": {Path("core/cache.py")},
    # queue.py owns enqueueing; jobs/worker.py is the worker entry point and is
    # infrastructure, not application code.
    "arq": {Path("core/queue.py"), Path("jobs/worker.py")},
}


def _python_files() -> list[Path]:
    return sorted(p for p in APP_DIR.rglob("*.py"))


def test_no_direct_redis_imports() -> None:
    offenders = []
    for path in _python_files():
        relative = path.relative_to(APP_DIR)
        if relative in ALLOWED["redis"]:
            continue
        if REDIS_IMPORT.search(path.read_text(encoding="utf-8")):
            offenders.append(str(relative))
    assert offenders == [], f"import the CacheClient instead (section 3A): {offenders}"


def test_no_direct_arq_imports() -> None:
    offenders = []
    for path in _python_files():
        relative = path.relative_to(APP_DIR)
        if relative in ALLOWED["arq"]:
            continue
        if ARQ_IMPORT.search(path.read_text(encoding="utf-8")):
            offenders.append(str(relative))
    assert offenders == [], f"import the QueueClient instead (section 3A): {offenders}"
