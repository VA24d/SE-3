#!/usr/bin/env python3
"""
Local NFR sampling for the technical report: HTTP redirect latency and WebSocket
relay fan-out latency / throughput (localhost, two peers per session).
"""
import asyncio
import argparse
import http.client
import statistics
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

IMPL_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = IMPL_ROOT / "src" / "server"
PORT = 8777


def parse_target_url(session_url: str | None):
    if not session_url:
        http_base = f"http://127.0.0.1:{PORT}"
        ws_uri = f"ws://127.0.0.1:{PORT}/ws/bench-latency"
        return http_base, ws_uri, True

    parsed = urlparse(session_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("session URL must look like http://host[:port]/app/?session=...")

    session_id = parse_qs(parsed.query).get("session", [""])[0].strip()
    if not session_id:
        raise ValueError("session URL must include a session query parameter")

    http_base = f"{parsed.scheme}://{parsed.netloc}"
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_uri = f"{ws_scheme}://{parsed.netloc}/ws/{session_id}"
    return http_base, ws_uri, False


def http_redirect_samples(http_base: str, n: int = 40):
    times_ms = []
    parsed = urlparse(http_base)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    for _ in range(n):
        t0 = time.perf_counter()
        conn = conn_cls(parsed.hostname, parsed.port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        times_ms.append((time.perf_counter() - t0) * 1000)
    return times_ms


async def ws_fanout_samples(ws_uri: str, samples: int = 40):
    import websockets

    payload = b"\x00\x01\x02\x03\x04"
    lat_ms = []
    for _ in range(samples):
        async with websockets.connect(ws_uri) as a, websockets.connect(ws_uri) as b:
            t0 = time.perf_counter()
            await a.send(payload)
            _ = await b.recv()
            lat_ms.append((time.perf_counter() - t0) * 1000)
    return lat_ms


async def ws_throughput_msgs_per_s(ws_uri: str, count: int = 400):
    import websockets

    payload = b"\x00" + b"x" * 128
    async with websockets.connect(ws_uri) as sender, websockets.connect(ws_uri) as recv:
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
    parser = argparse.ArgumentParser(description="Sample SyncSpace relay metrics.")
    parser.add_argument(
        "--session-url",
        help="Target a running server using a shared /app/?session=... link instead of launching a local server.",
    )
    args = parser.parse_args()

    proc = None
    http_base, ws_uri, launched_local_server = parse_target_url(args.session_url)

    if launched_local_server:
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
        http_ms = http_redirect_samples(http_base, 40)
        lat_ms = asyncio.run(ws_fanout_samples(ws_uri, 40))
        tput = asyncio.run(ws_throughput_msgs_per_s(ws_uri, 400))

        h = summarize_ms(http_ms)
        w = summarize_ms(lat_ms)

        print("SyncSpace — local NFR samples (see Technical report.md for interpretation)")
        print(f"Target HTTP base: {http_base}")
        print(f"Target WebSocket: {ws_uri}")
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
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
