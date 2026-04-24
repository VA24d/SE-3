"""
Prefer the project virtualenv for test scripts so `python3 tests/…` works after
`make install` without activating .venv. Falls back to the current interpreter.
"""
import os
import subprocess
import sys
from pathlib import Path

_IMPL_ROOT = Path(__file__).resolve().parents[1]


def venv_python() -> Path | None:
    if sys.platform == "win32":
        p = _IMPL_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        p = _IMPL_ROOT / ".venv" / "bin" / "python"
    return p if p.is_file() else None


def _deps_ok(py: str) -> bool:
    r = subprocess.run(
        [py, "-c", "import uvicorn, websockets"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.returncode == 0


def _in_project_venv() -> bool:
    """True if this interpreter is the project venv (uses sys.prefix; not sys.executable — venv may symlink to the same base binary as the system)."""
    try:
        return Path(sys.prefix).resolve() == (_IMPL_ROOT / ".venv").resolve()
    except OSError:
        return False


def reexec_in_venv_if_better(entry_script: Path) -> None:
    """
    If .venv exists and has dependencies but the current interpreter does not,
    re-exec entry_script with .venv’s python so the server subprocess and test share one env.
    """
    venv = venv_python()
    if venv is None:
        return
    if _in_project_venv():
        return
    if not _deps_ok(str(venv)):
        return
    if _deps_ok(sys.executable):
        return
    os.execv(str(venv), [str(venv), str(entry_script.resolve()), *sys.argv[1:]])


def _websockets_ok(py: str) -> bool:
    r = subprocess.run(
        [py, "-c", "import websockets"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.returncode == 0


def require_test_deps() -> int | None:
    """
    If uvicorn/websockets are missing, print how to install and return exit code 1.
    Return None if OK to continue.
    """
    if _deps_ok(sys.executable):
        return None
    msg = (
        "This test needs `uvicorn` and `websockets`.\n"
        f"From the Implementation directory run:\n"
        f"  make install   # or:  {sys.executable} -m pip install -r requirements.txt\n"
        f"  make test-smoke\n"
        f"Or activate .venv and run this script again."
    )
    print(msg, file=sys.stderr)
    return 1


def require_websockets() -> int | None:
    """For benchmarks that only talk to a remote server (no local uvicorn)."""
    if _websockets_ok(sys.executable):
        return None
    msg = (
        "This script needs the `websockets` package for client connections.\n"
        f"From the Implementation directory run:\n"
        f"  make install   # or:  {sys.executable} -m pip install -r requirements.txt\n"
        f"Or:  {sys.executable} -m pip install websockets"
    )
    print(msg, file=sys.stderr)
    return 1


def python_for_uvicorn_subprocess() -> str:
    """Python binary to use for `python -m uvicorn` in tests (prefers .venv if present)."""
    v = venv_python()
    if v is not None and _deps_ok(str(v)):
        return str(v)
    return sys.executable
