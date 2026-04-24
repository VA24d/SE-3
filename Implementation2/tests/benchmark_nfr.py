#!/usr/bin/env python3
"""
NFR benchmark for Implementation 2: OT + Central Sequencer.

Measures and compares against the same metrics as Implementation 1's
benchmark_nfr.py so results are directly comparable:
  1. HTTP redirect latency (40 samples)
  2. WebSocket op round-trip latency: sender→server transforms→receiver (40 samples)
  3. Sequential throughput: ops/s with ack-gated send (400 ops)

Key differences from Impl-1 benchmark:
  - Wire format is JSON (not binary), so frame sizes are larger.
  - Server executes _transform_op() + _apply_op() on every message.
  - Throughput test waits for ACK before each send (realistic OT usage).
"""
import asyncio
import http.client
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

IMPL_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = IMPL_ROOT / "src" / "server"
PORT = 8782  # different from Impl-1's 8777 so both can run simultaneously


# ── HTTP redirect latency ─────────────────────────────────────────────────────

def http_redirect_samples(n: int = 40):
    times_ms = []
    for _ in range(n):
        t0 = time.perf_counter()
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        times_ms.append((time.perf_counter() - t0) * 1000)
    return times_ms


# ── WebSocket op latency ──────────────────────────────────────────────────────

async def _drain_until(ws, mtype: str, timeout: float = 2.0) -> dict:
    """Receive messages until one of the target type arrives."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        if msg["type"] == mtype:
            return msg


async def ws_op_latency(samples: int = 40):
    """
    Round-trip latency: client A sends one-char insert op, measure time until
    client B receives the broadcast (after server transforms and re-broadcasts).
    """
    import websockets
    lat_ms = []
    for _ in range(samples):
        async with (
            websockets.connect(f"ws://127.0.0.1:{PORT}/ws/bench-lat") as a,
            websockets.connect(f"ws://127.0.0.1:{PORT}/ws/bench-lat") as b,
        ):
            init_a = await _drain_until(a, "init")
            await _drain_until(b, "init")
            # drain join notifications
            for ws in (a, b):
                try:
                    await asyncio.wait_for(ws.recv(), timeout=0.3)
                except asyncio.TimeoutError:
                    pass

            rev = init_a["rev"]
            t0 = time.perf_counter()
            await a.send(json.dumps({
                "type": "op", "rev": rev,
                "ops": [{"type": "insert", "pos": 0, "text": "x"}],
            }))
            await _drain_until(b, "op")
            lat_ms.append((time.perf_counter() - t0) * 1000)
    return lat_ms


# ── Throughput (ack-gated sequential ops) ─────────────────────────────────────

async def ws_throughput_ops_per_s(count: int = 400):
    """
    Sequential throughput with ACK gating: send op → wait for ack → send next.
    This is the realistic OT usage pattern (one inflight op at a time).
    Measures total ops delivered from sender to receiver per second.
    """
    import websockets
    async with (
        websockets.connect(f"ws://127.0.0.1:{PORT}/ws/bench-tput") as sender,
        websockets.connect(f"ws://127.0.0.1:{PORT}/ws/bench-tput") as recvr,
    ):
        init_s = await _drain_until(sender, "init")
        await _drain_until(recvr, "init")
        for ws in (sender, recvr):
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.3)
            except asyncio.TimeoutError:
                pass

        current_rev = init_s["rev"]
        t0 = time.perf_counter()

        for _ in range(count):
            await sender.send(json.dumps({
                "type": "op", "rev": current_rev,
                "ops": [{"type": "insert", "pos": 0, "text": "x"}],
            }))
            # Wait for server ack before sending next (classic OT flow).
            ack = await _drain_until(sender, "ack", timeout=5)
            current_rev = ack["rev"]

        elapsed = time.perf_counter() - t0
    return count / elapsed if elapsed > 0 else 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def summarize_ms(values):
    return {
        "mean_ms":   statistics.mean(values),
        "median_ms": statistics.median(values),
        "min_ms":    min(values),
        "max_ms":    max(values),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    env = {**__import__("os").environ,
           "SYNCSPACE_OT_HOST": "127.0.0.1",
           "SYNCSPACE_OT_PORT": str(PORT)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(SERVER_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)
    if proc.poll() is not None:
        print("Server failed to start.", file=sys.stderr)
        return 1

    try:
        http_ms = http_redirect_samples(40)
        lat_ms  = asyncio.run(ws_op_latency(40))
        tput    = asyncio.run(ws_throughput_ops_per_s(400))

        h = summarize_ms(http_ms)
        w = summarize_ms(lat_ms)

        print("SyncSpace-OT — NFR benchmark (Implementation 2: OT + Central Sequencer)")
        print()
        print("HTTP GET / (redirect), 40 samples:")
        print(f"  mean={h['mean_ms']:.3f} ms  median={h['median_ms']:.3f} ms  "
              f"min={h['min_ms']:.3f} ms  max={h['max_ms']:.3f} ms")
        print()
        print("WebSocket OT op round-trip (insert -> server xform -> peer broadcast), 40 samples:")
        print(f"  mean={w['mean_ms']:.3f} ms  median={w['median_ms']:.3f} ms  "
              f"min={w['min_ms']:.3f} ms  max={w['max_ms']:.3f} ms")
        print()
        print(f"WebSocket OT throughput (ack-gated sequential): {tput:.1f} ops/s "
              f"(400 ops, JSON frames, server transforms each)")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
