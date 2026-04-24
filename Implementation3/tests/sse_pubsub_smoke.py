#!/usr/bin/env python3
"""Smoke test: temporary server, one SSE subscriber; POST from another connection id is delivered."""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

IMPL = Path(__file__).resolve().parents[1]
SERVER_DIR = IMPL / "src" / "server"
PORT = 8783
SESSION = "smoke-ps"
BASE = f"http://127.0.0.1:{PORT}"


async def read_first_data_line(client: httpx.AsyncClient, conn: str) -> dict:
    url = f"{BASE}/api/sessions/{SESSION}/stream"
    async with client.stream(
        "GET",
        url,
        params={"connection_id": conn, "client_id": 1},
        timeout=60.0,
    ) as r:
        r.raise_for_status()
        buf = b""
        async for chunk in r.aiter_bytes():
            buf += chunk
            if b"\n\n" in buf:
                break
            if len(buf) > 2_000_000:
                raise RuntimeError("SSE buffer too large")
    text = buf.decode("utf-8", errors="replace")
    for line in text.split("\n"):
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise RuntimeError(f"no data: line in {text[:400]!r}")


async def amain() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(SERVER_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        await asyncio.sleep(1.2)
        if proc.poll() is not None:
            err = proc.stderr.read().decode() if proc.stderr else ""
            print("Server failed to start:", err, file=sys.stderr)
            return 1

        c1 = "11111111-1111-1111-1111-111111111111"
        c2 = "22222222-2222-2222-2222-222222222222"

        async with httpx.AsyncClient(timeout=60.0) as client:
            peer = asyncio.create_task(read_first_data_line(client, c2))
            await asyncio.sleep(0.35)

            env = {"kind": "json", "text": '{"type":"smoke","ok":true}'}
            r = await client.post(
                f"{BASE}/api/sessions/{SESSION}/publish",
                json={"from_connection": c1, "envelope": env},
            )
            r.raise_for_status()

            b_data = await peer
            if b_data.get("kind") != "json":
                print("sse_pubsub_smoke: FAIL", b_data, file=sys.stderr)
                return 1
            if json.loads(b_data["text"]).get("ok") is not True:
                print("sse_pubsub_smoke: FAIL payload", file=sys.stderr)
                return 1

        print("sse_pubsub_smoke: OK (pub-sub fan-out to peer SSE)")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
