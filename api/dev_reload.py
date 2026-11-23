"""Dev-only API runner: one uvicorn process, restarted cleanly on save.

Why not `uvicorn --reload`? Its reloader restarts through ``multiprocessing``,
and on this project's Windows machines that child is spawned with the *base*
interpreter instead of ``.venv``, and after the first change the reloader
wedges: the old server keeps serving, the new one never starts, and a route
added a minute ago keeps answering 404 until the server is killed by hand.
That made "save and test the new endpoint" unreliable.

This runner is deliberately dumb and observable: it starts uvicorn as a direct
child with ``sys.executable`` (the interpreter ``.venv`` provides), watches
``api/app`` for ``.py`` changes, and on a change stops that child and starts a
new one. No threads, no fork, no inherited socket — so a restart is the same
thing a manual restart is.

Usage (through the project runner, so PYTHONPATH and the venv are set up):

    npm run dev:api
    npm run dev:api -- --port 8001     # extra args go to uvicorn
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from watchfiles import PythonFilter, watch

ROOT = Path(__file__).resolve().parent.parent
WATCHED = ROOT / "api" / "app"

HOST = "127.0.0.1"
PORT = "8000"


def _command(extra: list[str]) -> list[str]:
    # A list, never a string: the repository path contains spaces.
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        PORT,
        *extra,
    ]


def _start(command: list[str], *, settle: float = 1.5) -> subprocess.Popen[bytes]:
    """Start uvicorn and give it a moment to prove it did not die on the spot.

    A restart can race the port being released by the process just stopped, and
    a child that exits immediately would otherwise leave a dead server behind a
    supervisor that keeps saying it is watching. One retry covers the race; a
    second failure is reported loudly rather than hidden.
    """
    for attempt in (1, 2):
        print(f"[dev:api] starting on http://{HOST}:{PORT}", flush=True)
        child = subprocess.Popen(command, cwd=str(ROOT))
        time.sleep(settle)
        if child.poll() is None:
            return child
        print(
            f"[dev:api] the server exited straight away (code {child.returncode})"
            + (" — trying once more" if attempt == 1 else " — fix that, then save a file"),
            flush=True,
        )
        time.sleep(1.0)
    return child


def _stop(child: subprocess.Popen[bytes], timeout: float = 15.0) -> None:
    """Stop one child and wait for it, so the port is free before the next start."""
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print("[dev:api] child ignored terminate; killing it", flush=True)
        child.kill()
        child.wait(timeout=timeout)


def main() -> int:
    extra = sys.argv[1:]
    command = _command(extra)
    child = _start(command)
    print(f"[dev:api] watching {WATCHED} — save a .py file to restart. Ctrl-C stops.", flush=True)

    try:
        for changes in watch(WATCHED, watch_filter=PythonFilter(), debounce=300, step=50):
            if child.poll() is not None:
                print(f"[dev:api] child had exited with code {child.returncode}", flush=True)
            files = sorted({Path(path).relative_to(ROOT).as_posix() for _change, path in changes})
            shown = ", ".join(files[:3]) + (" …" if len(files) > 3 else "")
            print(f"[dev:api] changed: {shown} — restarting", flush=True)
            _stop(child)
            child = _start(command)
    except KeyboardInterrupt:
        pass
    finally:
        _stop(child)
        print("[dev:api] stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
