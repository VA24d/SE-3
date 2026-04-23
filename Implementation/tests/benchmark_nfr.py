#!/usr/bin/env python3
"""
Local NFR sampling for the technical report: HTTP redirect latency and WebSocket
relay fan-out latency / throughput (localhost, two peers per session).
"""
import asyncio
import http.client
import statistics
import subprocess
import sys
import time
from pathlib import Path

IMPL_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = IMPL_ROOT / "src" / "server"
PORT = 8777


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


async def ws_fanout_samples(samples: int = 40):
    import websockets

    uri = f"ws://127.0.0.1:{PORT}/ws/bench-latency"
    payload = b"\x00\x01\x02\x03\x04"
    lat_ms = []
    for _ in range(samples):
        async with websockets.connect(uri) as a, websockets.connect(uri) as b:
            t0 = time.perf_counter()
            await a.send(payload)
            _ = await b.recv()
            lat_ms.append((time.perf_counter() - t0) * 1000)
    return lat_ms


async def ws_throughput_msgs_per_s(count: int = 400):
    import websockets

    uri = f"ws://127.0.0.1:{PORT}/ws/bench-tput"
    payload = b"\x00" + b"x" * 128
    async with websockets.connect(uri) as sender, websockets.connect(uri) as recv:
        t0 = time.perf_counter()
        for _ in range(count):
            await sender.send(payload)
            _ = await recv.recv()
        elapsed = time.perf_counter() - t0
    return count / elapsed if elapsed > 0 else 0.0


def summarize_ms(values):
    return {
        "mean_ms": statistics.mean(values),
        "median_ms": statistics.median(values),
        "min_ms": min(values),
        "max_ms": max(values),
    }


def main() -> int:
    proc = subprocess.Popen(
        [
            sys.executable,
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
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.2)
    if proc.poll() is not None:
        print("Server failed to start.", file=sys.stderr)
        return 1
    try:
        http_ms = http_redirect_samples(40)
        lat_ms = asyncio.run(ws_fanout_samples(40))
        tput = asyncio.run(ws_throughput_msgs_per_s(400))

        h = summarize_ms(http_ms)
        w = summarize_ms(lat_ms)

        print("SyncSpace — local NFR samples (see Technical report.md for interpretation)")
        print()
        print("HTTP GET / (redirect to /app/?session=…), 40 samples:")
        print(f"  mean={h['mean_ms']:.3f} ms  median={h['median_ms']:.3f} ms  "
              f"min={h['min_ms']:.3f} ms  max={h['max_ms']:.3f} ms")
        print()
        print("WebSocket relay: one client sends 5-byte frame, peer receives, 40 samples:")
        print(f"  mean={w['mean_ms']:.3f} ms  median={w['median_ms']:.3f} ms  "
              f"min={w['min_ms']:.3f} ms  max={w['max_ms']:.3f} ms")
        print()
        print(f"WebSocket relay throughput: {tput:.1f} messages/s "
              f"(400 round-trips, 129-byte binary frames)")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
