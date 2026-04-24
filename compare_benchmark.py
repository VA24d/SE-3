#!/usr/bin/env python3
"""
compare_benchmark.py — implementation-agnostic NFR benchmark.

Runs the SAME three metrics against both implementations and prints a
side-by-side comparison table.

  Metric 1  HTTP redirect latency          (40 samples each)
  Metric 2  WebSocket 1-hop latency        (40 samples each)
            A sends one edit → B receives it — measured end-to-end.
  Metric 3  Throughput: edits/s            (400 ops each, sequential)

Protocol differences are encapsulated in ImplDriver subclasses.
The benchmark functions (http_latency, ws_latency, ws_throughput) are
identical for both drivers — they call abstract methods that each driver
implements to match its wire protocol.

  CRDTDriver  binary frames, relay just forwards, receiver confirms delivery
  OTDriver    JSON text, server transforms + acks, sender waits for ack

Usage (from SE-3/ directory):
    python compare_benchmark.py

Both venvs must be installed first:
    cd Implementation  && make install
    cd Implementation2 && make install
"""

import asyncio
import http.client
import json
import os
import statistics
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path

SE3_ROOT = Path(__file__).resolve().parent


# ── Venv / Python helpers ─────────────────────────────────────────────────────

def _venv_python(venv_root: Path) -> str | None:
    """Return path to the venv's Python binary, or None if not found."""
    p = venv_root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return str(p) if p.is_file() else None


def _has_deps(py: str, *modules: str) -> bool:
    code = "; ".join(f"import {m}" for m in modules)
    return subprocess.run([py, "-c", code], capture_output=True, timeout=10).returncode == 0


def _best_python(venv_root: Path, *required: str) -> str:
    """Return the best Python that has all required modules."""
    for py in filter(None, [_venv_python(venv_root), sys.executable]):
        if _has_deps(py, *required):
            return py
    sys.exit(
        f"Cannot find a Python with {required} for {venv_root}.\n"
        f"Run:  cd {venv_root.parent.name} && make install"
    )


# ── Abstract driver ───────────────────────────────────────────────────────────

class ImplDriver(ABC):
    """
    Encapsulates the wire-protocol details of one implementation so that the
    benchmark functions above it stay identical for both architectures.
    """

    # Subclasses set these as class attributes.
    name: str
    port: int        # benchmark port (must differ between drivers)
    server_dir: Path # directory that contains server.py
    server_env: dict # extra environment variables for the subprocess
    venv_root: Path  # root of the implementation's .venv

    # ── Protocol hooks (must be implemented) ─────────────────────────────────

    @abstractmethod
    async def init_pair(self, ws_a, ws_b) -> dict:
        """
        Consume any handshake messages that arrive immediately after two
        clients connect to a fresh session.  Returns a state dict (may be
        empty) that is threaded through subsequent calls.
        """

    @abstractmethod
    async def send_edit(self, ws, state: dict) -> dict:
        """Send one 'edit' from ws.  Return updated state (e.g. new rev)."""

    @abstractmethod
    async def recv_broadcast(self, ws) -> None:
        """Wait for one edit broadcast to arrive at ws (the receiving peer)."""

    @abstractmethod
    async def throughput_confirm(self, ws_sender, ws_receiver, state: dict) -> dict:
        """
        Wait for the confirmation that is natural to this architecture:
          CRDT → receiver has the message   (end-to-end delivery)
          OT   → sender has the server ack  (server-confirmed processing)
        Return updated state.
        """

    # ── Shared helpers ────────────────────────────────────────────────────────

    def best_python(self) -> str:
        return _best_python(self.venv_root, "uvicorn", "websockets")

    def connect_uri(self, session: str) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/{session}"


# ── CRDT driver (Implementation 1) ───────────────────────────────────────────

class CRDTDriver(ImplDriver):
    """
    Implementation 1: stateless relay, binary wire format.
    Server does zero computation — it just calls send_bytes on each peer.
    Confirmation = the receiving peer gets the frame (end-to-end delivery).
    """
    name       = "Impl-1  CRDT + Stateless Relay"
    port       = 8971   # benchmark-only port, won't clash with dev (8080) or Impl-1 bench (8777)
    server_dir = SE3_ROOT / "Implementation" / "src" / "server"
    server_env = {}
    venv_root  = SE3_ROOT / "Implementation" / ".venv"

    _PAYLOAD = b"\x00" + b"x" * 4   # prefix 0x00 = doc update (5 bytes)

    async def init_pair(self, ws_a, ws_b) -> dict:
        # Relay sends no handshake; nothing to consume.
        return {}

    async def send_edit(self, ws, state: dict) -> dict:
        await ws.send(self._PAYLOAD)
        return state

    async def recv_broadcast(self, ws) -> None:
        await ws.recv()

    async def throughput_confirm(self, ws_sender, ws_receiver, state: dict) -> dict:
        # Natural CRDT confirmation: peer received the frame.
        await ws_receiver.recv()
        return state


# ── OT driver (Implementation 2) ─────────────────────────────────────────────

class OTDriver(ImplDriver):
    """
    Implementation 2: central sequencer, JSON wire format.
    Server transforms every op and broadcasts canonical ops.
    Confirmation = server ack (the protocol requires this before next send).
    """
    name       = "Impl-2  OT + Central Sequencer"
    port       = 8972   # benchmark-only port, won't clash with dev (8081) or Impl-2 bench (8782)
    server_dir = SE3_ROOT / "Implementation2" / "src" / "server"
    server_env = {"SYNCSPACE_OT_PORT": "8972"}
    venv_root  = SE3_ROOT / "Implementation2" / ".venv"

    async def _drain_until(self, ws, mtype: str, timeout: float = 3.0) -> dict:
        """Read messages from ws until one with the target 'type' arrives."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"Timed out waiting for '{mtype}'")
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            if msg.get("type") == mtype:
                return msg

    async def init_pair(self, ws_a, ws_b) -> dict:
        # Server sends 'init' to each new client and 'join' to existing peers.
        init_a = await self._drain_until(ws_a, "init")
        await self._drain_until(ws_b, "init")
        # ws_a gets a 'join' about ws_b; drain it so it doesn't poison later reads.
        for ws in (ws_a, ws_b):
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.4)
            except asyncio.TimeoutError:
                pass
        return {"rev": init_a["rev"]}

    def _op_msg(self, rev: int) -> str:
        return json.dumps({
            "type": "op", "rev": rev,
            "ops": [{"type": "insert", "pos": 0, "text": "x"}],
        })

    async def send_edit(self, ws, state: dict) -> dict:
        await ws.send(self._op_msg(state["rev"]))
        return state

    async def recv_broadcast(self, ws) -> None:
        await self._drain_until(ws, "op")

    async def throughput_confirm(self, ws_sender, ws_receiver, state: dict) -> dict:
        # Natural OT confirmation: server ack (required before next send).
        ack = await self._drain_until(ws_sender, "ack", timeout=5)
        return {**state, "rev": ack["rev"]}


# ── Server lifecycle ──────────────────────────────────────────────────────────

def start_server(driver: ImplDriver) -> subprocess.Popen:
    env = {**os.environ, **driver.server_env}
    py  = driver.best_python()
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(driver.port)],
        cwd=str(driver.server_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)
    if proc.poll() is not None:
        raise RuntimeError(f"Server for '{driver.name}' failed to start (port {driver.port})")
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ── Metric 1: HTTP redirect latency ──────────────────────────────────────────

def http_latency_samples(port: int, n: int = 40) -> list[float]:
    """GET / and measure round-trip until the redirect response is fully read."""
    times_ms = []
    for _ in range(n):
        t0 = time.perf_counter()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/")
        conn.getresponse().read()
        conn.close()
        times_ms.append((time.perf_counter() - t0) * 1000)
    return times_ms


# ── Metric 2: WebSocket 1-hop latency ────────────────────────────────────────

async def ws_latency_samples(driver: ImplDriver, n: int = 40) -> list[float]:
    """
    Fresh session pair per sample (independent, no state carry-over).
    Clock starts just before A sends; stops when B receives the broadcast.
    This is identical for both drivers — protocol differences are in the hooks.
    """
    import websockets

    lat_ms = []
    for i in range(n):
        uri = driver.connect_uri(f"bench-lat-{i}")
        async with websockets.connect(uri) as ws_a, websockets.connect(uri) as ws_b:
            state = await driver.init_pair(ws_a, ws_b)
            t0 = time.perf_counter()
            await driver.send_edit(ws_a, state)
            await driver.recv_broadcast(ws_b)
            lat_ms.append((time.perf_counter() - t0) * 1000)
    return lat_ms


# ── Metric 3: Sustained throughput ───────────────────────────────────────────

async def ws_throughput(driver: ImplDriver, count: int = 400) -> float:
    """
    One persistent session pair; send `count` sequential edits and measure
    how many are processed per second.

    'Sequential' means: send one edit, wait for the architecture-appropriate
    confirmation, then send the next.  This is the realistic usage pattern
    for both:
      CRDT — wait for receiver to get each frame  (natural flow)
      OT   — wait for server ack before each send  (protocol requirement)
    """
    import websockets

    uri = driver.connect_uri("bench-tput")
    async with websockets.connect(uri) as ws_a, websockets.connect(uri) as ws_b:
        state = await driver.init_pair(ws_a, ws_b)
        t0 = time.perf_counter()
        for _ in range(count):
            state = await driver.send_edit(ws_a, state)
            state = await driver.throughput_confirm(ws_a, ws_b, state)
        elapsed = time.perf_counter() - t0
    return count / elapsed if elapsed > 0 else 0.0


# ── Stats + display ───────────────────────────────────────────────────────────

def _stats(values: list[float]) -> dict:
    return {
        "mean":   statistics.mean(values),
        "median": statistics.median(values),
        "min":    min(values),
        "max":    max(values),
        "stdev":  statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def _ratio(a: float, b: float) -> str:
    if b == 0:
        return "  n/a"
    r = a / b
    arrow = "^" if r >= 1 else "v"
    return f"{r:5.2f}x {arrow}"


def print_comparison(
    drivers: list[ImplDriver],
    http_stats: list[dict],
    lat_stats:  list[dict],
    tputs:      list[float],
) -> None:
    d0, d1 = drivers
    s0, s1 = lat_stats
    h0, h1 = http_stats

    W = 72
    col = 18

    def row(label, v0, v1, unit="ms", higher_is_better=False):
        ratio = v1 / v0 if v0 else float("nan")
        if higher_is_better:
            winner = "<-- faster" if v0 > v1 else ("faster -->" if v1 > v0 else "  equal")
        else:
            winner = "<-- faster" if v0 < v1 else ("faster -->" if v1 < v0 else "  equal")
        print(f"  {label:<26} {v0:{col}.3f} {unit}   {v1:{col}.3f} {unit}   {ratio:.2f}x  {winner}")

    sep = "=" * W
    thin = "-" * W

    print()
    print(sep)
    print(f"  {'NFR Comparison':^{W-2}}")
    print(sep)
    print(f"  {'Metric':<26} {d0.name:<{col+4}} {d1.name:<{col+4}} Ratio")
    print(thin)

    print()
    print(f"  HTTP redirect latency — 40 samples (lower is better)")
    row("  mean",   h0["mean"],   h1["mean"])
    row("  median", h0["median"], h1["median"])

    print()
    print(f"  WebSocket 1-hop latency — 40 samples, fresh session per sample (lower is better)")
    print(f"  [A sends one edit -> B receives it, clock covers send + relay/xform + recv]")
    row("  mean",   s0["mean"],   s1["mean"])
    row("  median", s0["median"], s1["median"])
    row("  min",    s0["min"],    s1["min"])
    row("  max",    s0["max"],    s1["max"])
    row("  stdev",  s0["stdev"],  s1["stdev"])

    print()
    print(f"  Throughput — 400 sequential edits, persistent session (higher is better)")
    confirm_note = [
        "receiver delivery (fire-and-forward)",
        "server ack (OT protocol constraint)",
    ]
    for i, (d, t, note) in enumerate(zip(drivers, tputs, confirm_note)):
        print(f"  [{d.name}]  confirmation: {note}")
    ratio_t = tputs[0] / tputs[1] if tputs[1] else float("nan")
    winner_t = "<-- higher" if tputs[0] > tputs[1] else "higher -->"
    print(f"  {'  ops/s':<26} {tputs[0]:{col}.1f} ops/s {tputs[1]:{col}.1f} ops/s {ratio_t:.2f}x  {winner_t}")

    print()
    print(thin)
    print("  Ratio column: Impl-1 / Impl-2.  >1 = Impl-1 is higher for that metric.")
    print("  For latency (lower=better): ratio >1 means Impl-1 is SLOWER.")
    print("  For throughput (higher=better): ratio >1 means Impl-1 is FASTER.")
    print(sep)
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    # Check websockets is available in THIS interpreter (needed for the async
    # benchmark coroutines that run in-process, not in a subprocess).
    if not _has_deps(sys.executable, "websockets"):
        # Try to re-exec with a venv that has it.
        for impl in ("Implementation", "Implementation2"):
            venv = SE3_ROOT / impl / ".venv"
            py = _venv_python(venv)
            if py and _has_deps(py, "websockets"):
                os.execv(py, [py, str(Path(__file__).resolve()), *sys.argv[1:]])
        sys.exit(
            "The 'websockets' package is required.\n"
            "Run:  cd Implementation && make install\n"
            "Then: python compare_benchmark.py"
        )

    drivers: list[ImplDriver] = [CRDTDriver(), OTDriver()]
    procs: list[subprocess.Popen] = []

    print("Starting servers...")
    try:
        for d in drivers:
            print(f"  {d.name}  (port {d.port})")
            procs.append(start_server(d))
        print("  Both servers ready.")
        print()

        results_http: list[dict] = []
        results_lat:  list[dict] = []
        results_tput: list[float] = []

        for d in drivers:
            print(f"Benchmarking {d.name}...")
            print("  HTTP latency...", end=" ", flush=True)
            http_ms = http_latency_samples(d.port, n=40)
            print("done.")

            print("  WebSocket latency...", end=" ", flush=True)
            lat_ms = asyncio.run(ws_latency_samples(d, n=40))
            print("done.")

            print("  Throughput...", end=" ", flush=True)
            tput = asyncio.run(ws_throughput(d, count=400))
            print("done.")
            print()

            results_http.append(_stats(http_ms))
            results_lat.append(_stats(lat_ms))
            results_tput.append(tput)

        print_comparison(drivers, results_http, results_lat, results_tput)
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    finally:
        for p in procs:
            stop_server(p)


if __name__ == "__main__":
    raise SystemExit(main())
