#!/usr/bin/env python3
"""Smoke test: start uvicorn and verify the WebSocket relay forwards frames between two clients."""
import asyncio
import subprocess
import sys
import time
from pathlib import Path

from test_runtime import (
    python_for_uvicorn_subprocess,
    reexec_in_venv_if_better,
    require_test_deps,
)

IMPL_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = IMPL_ROOT / "src" / "server"
PORT = 8765
WS_URI = f"ws://127.0.0.1:{PORT}/ws/smoke-session"
_ENTRY = Path(__file__).resolve()


async def relay_binary_ok():
    import websockets

    payload = b"\x00\x01\x02\x03"
    async with websockets.connect(WS_URI) as ws1:
        async with websockets.connect(WS_URI) as ws2:
            await ws1.send(payload)
            got = await asyncio.wait_for(ws2.recv(), timeout=5.0)
            assert got == payload, (got, payload)


async def relay_json_text_ok():
    import websockets

    text = '{"type":"request_state"}'
    async with websockets.connect(WS_URI) as ws1:
        async with websockets.connect(WS_URI) as ws2:
            await ws1.send(text)
            got = await asyncio.wait_for(ws2.recv(), timeout=5.0)
            assert got == text, (got, text)


def root_redirects_to_app():
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    conn.request("GET", "/")
    resp = conn.getresponse()
    try:
        assert resp.status in (301, 302, 303, 307, 308), resp.status
        loc = resp.getheader("Location") or ""
        assert "/app/" in loc and "session=" in loc, loc
    finally:
        resp.read()
        conn.close()


def main() -> int:
    reexec_in_venv_if_better(_ENTRY)
    err = require_test_deps()
    if err is not None:
        return err
    py = python_for_uvicorn_subprocess()
    proc = subprocess.Popen(
        [
            py,
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=str(SERVER_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(1.2)
        if proc.poll() is not None:
            err = proc.stderr.read().decode() if proc.stderr else ""
            print("Server failed to start:", err, file=sys.stderr)
            return 1

        async def run():
            await relay_binary_ok()
            await relay_json_text_ok()

        root_redirects_to_app()
        asyncio.run(run())
        print("ws_relay_smoke: OK (redirect + binary relay + text relay)")
        return 0
    except Exception as e:
        print("ws_relay_smoke: FAIL", e, file=sys.stderr)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
