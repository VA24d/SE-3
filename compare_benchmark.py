#!/usr/bin/env python3
"""
compare_benchmark.py — implementation-agnostic NFR benchmark.

Runs the SAME three metrics against all implementations and prints a
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

Remote servers (shared links from other laptops):
    python compare_benchmark.py \
      --impl1-url "http://10.0.0.21:8080/app/?session=abc123" \
      --impl2-url "http://10.0.0.22:8081/app/?session=def456" \
      --impl3-url "http://10.0.0.23:8082/app/?session=ghi789"

All venvs must be installed first:
    cd Implementation  && make install
    cd Implementation2 && make install
    cd Implementation3 && make install
"""

import argparse
import asyncio
import http.client
import json
import os
import statistics
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

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

    @abstractmethod
    def open_pair(self, session: str):
        """Return an async context manager yielding (sender_endpoint, receiver_endpoint)."""

    # ── Shared helpers ────────────────────────────────────────────────────────

    def best_python(self) -> str:
        return _best_python(self.venv_root, "uvicorn")

    def http_base(self) -> str:
        return getattr(self, "_http_base", f"http://127.0.0.1:{self.port}")

    def configure_remote(self, app_url: str) -> None:
        parsed = urlparse(app_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                f"Invalid URL for {self.name}: {app_url}. Expected http(s)://host[:port]/app/?session=..."
            )
        self._http_base = f"{parsed.scheme}://{parsed.netloc}"
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        self._ws_base = f"{ws_scheme}://{parsed.netloc}/ws"

    def connect_uri(self, session: str) -> str:
        ws_base = getattr(self, "_ws_base", f"ws://127.0.0.1:{self.port}/ws")
        return f"{ws_base}/{session}"


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

    @asynccontextmanager
    async def open_pair(self, session: str):
        import websockets

        uri = self.connect_uri(session)
        async with websockets.connect(uri) as ws_a, websockets.connect(uri) as ws_b:
            yield ws_a, ws_b


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

    @asynccontextmanager
    async def open_pair(self, session: str):
        import websockets

        uri = self.connect_uri(session)
        async with websockets.connect(uri) as ws_a, websockets.connect(uri) as ws_b:
            yield ws_a, ws_b


# ── SSE Pub-Sub driver (Implementation 3) ───────────────────────────────────

class PubSubSSEDriver(ImplDriver):
    """
    Implementation 3: clients publish via HTTP POST and subscribe via SSE.
    Confirmation = receiver subscriber gets one forwarded envelope.
    """

    name = "Impl-3  Pub-Sub + SSE"
    port = 8973
    server_dir = SE3_ROOT / "Implementation3" / "src" / "server"
    server_env = {"SYNCSPACE_PUBSUB_PORT": "8973"}
    venv_root = SE3_ROOT / "Implementation3" / ".venv"

    def _stream_url(self, session: str) -> str:
        return f"{self.http_base()}/api/sessions/{session}/stream"

    def _publish_url(self, session: str) -> str:
        return f"{self.http_base()}/api/sessions/{session}/publish"

    @asynccontextmanager
    async def open_pair(self, session: str):
        import importlib

        httpx_mod = importlib.import_module("httpx")
        client = httpx_mod.AsyncClient(timeout=20.0)
        qa: asyncio.Queue[dict] = asyncio.Queue()
        qb: asyncio.Queue[dict] = asyncio.Queue()
        ready_a = asyncio.Event()
        ready_b = asyncio.Event()
        conn_a = f"bench-a-{session}"
        conn_b = f"bench-b-{session}"

        async def stream_worker(conn_id: str, q: asyncio.Queue, ready: asyncio.Event):
            params = {"connection_id": conn_id, "client_id": 1}
            async with client.stream("GET", self._stream_url(session), params=params) as resp:
                resp.raise_for_status()
                ready.set()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        q.put_nowait(json.loads(line[6:]))
                    except json.JSONDecodeError:
                        continue

        task_a = asyncio.create_task(stream_worker(conn_a, qa, ready_a))
        task_b = asyncio.create_task(stream_worker(conn_b, qb, ready_b))
        try:
            await asyncio.wait_for(asyncio.gather(ready_a.wait(), ready_b.wait()), timeout=5)
            sender = {"client": client, "connection_id": conn_a, "session": session, "queue": qa}
            receiver = {"client": client, "connection_id": conn_b, "session": session, "queue": qb}
            yield sender, receiver
        finally:
            task_a.cancel()
            task_b.cancel()
            await asyncio.gather(task_a, task_b, return_exceptions=True)
            await client.aclose()

    async def init_pair(self, ws_a, ws_b) -> dict:
        return {}

    async def send_edit(self, ws, state: dict) -> dict:
        payload = {
            "from_connection": ws["connection_id"],
            "envelope": {"kind": "json", "text": '{"type":"bench","x":1}'},
        }
        resp = await ws["client"].post(self._publish_url(ws["session"]), json=payload)
        resp.raise_for_status()
        return state

    async def recv_broadcast(self, ws) -> None:
        await asyncio.wait_for(ws["queue"].get(), timeout=5)

    async def throughput_confirm(self, ws_sender, ws_receiver, state: dict) -> dict:
        await asyncio.wait_for(ws_receiver["queue"].get(), timeout=5)
        return state


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

def http_latency_samples(http_base: str, n: int = 40) -> list[float]:
    """GET / and measure round-trip until the redirect response is fully read."""
    parsed = urlparse(http_base)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    host = parsed.hostname
    port = parsed.port
    times_ms = []
    for _ in range(n):
        t0 = time.perf_counter()
        conn = conn_cls(host, port, timeout=5)
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
    lat_ms = []
    for i in range(n):
        async with driver.open_pair(f"bench-lat-{i}") as (ws_a, ws_b):
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
    async with driver.open_pair("bench-tput") as (ws_a, ws_b):
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
    sep = "=" * 88
    thin = "-" * 88

    def _print_block(title: str, values: list[tuple[str, float]], lower_is_better: bool, unit: str):
        print()
        print(f"  {title}")
        ranked = sorted(values, key=lambda x: x[1], reverse=not lower_is_better)
        for idx, (name, value) in enumerate(ranked, start=1):
            print(f"    {idx}. {name:<34} {value:10.3f} {unit}")
        print(f"    best: {ranked[0][0]}")

    print()
    print(sep)
    print(f"  {'NFR Comparison (All Implementations)':^{len(sep)-2}}")
    print(sep)

    print()
    print("  Targets:")
    for d in drivers:
        print(f"    - {d.name} @ {d.http_base()}")

    _print_block(
        "HTTP redirect latency mean (40 samples, lower is better)",
        [(d.name, s["mean"]) for d, s in zip(drivers, http_stats)],
        lower_is_better=True,
        unit="ms",
    )

    _print_block(
        "Realtime 1-hop latency mean (40 samples, lower is better)",
        [(d.name, s["mean"]) for d, s in zip(drivers, lat_stats)],
        lower_is_better=True,
        unit="ms",
    )

    print()
    print("  Realtime 1-hop latency details (mean / median / min / max / stdev, ms):")
    for d, s in zip(drivers, lat_stats):
        print(
            f"    - {d.name:<34} "
            f"{s['mean']:.3f} / {s['median']:.3f} / {s['min']:.3f} / {s['max']:.3f} / {s['stdev']:.3f}"
        )

    _print_block(
        "Throughput (400 sequential updates, higher is better)",
        [(d.name, t) for d, t in zip(drivers, tputs)],
        lower_is_better=False,
        unit="ops/s",
    )

    print()
    print("  Throughput confirmation model:")
    for d in drivers:
        if isinstance(d, OTDriver):
            note = "server ack"
        else:
            note = "receiver delivery"
        print(f"    - {d.name}: {note}")

    print()
    print(thin)
    print("  Notes:")
    print("    - HTTP and transport means are best when LOWER.")
    print("    - Throughput is best when HIGHER.")
    print(sep)
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Implementation 1, 2, and 3 NFR metrics.")
    parser.add_argument(
        "--impl1-url",
        help="Shared URL for Implementation 1 server (http(s)://host[:port]/app/?session=...). If set, no local Impl-1 server is started.",
    )
    parser.add_argument(
        "--impl2-url",
        help="Shared URL for Implementation 2 server (http(s)://host[:port]/app/?session=...). If set, no local Impl-2 server is started.",
    )
    parser.add_argument(
        "--impl3-url",
        help="Shared URL for Implementation 3 server (http(s)://host[:port]/app/?session=...). If set, no local Impl-3 server is started.",
    )
    args = parser.parse_args()

    # Check websockets is available in THIS interpreter (needed for the async
    # benchmark coroutines that run in-process, not in a subprocess).
    required_runtime = ("websockets", "httpx")
    if not _has_deps(sys.executable, *required_runtime):
        # Try to re-exec with a venv that has it.
        for impl in ("Implementation", "Implementation2", "Implementation3"):
            venv = SE3_ROOT / impl / ".venv"
            py = _venv_python(venv)
            if py and _has_deps(py, *required_runtime):
                os.execv(py, [py, str(Path(__file__).resolve()), *sys.argv[1:]])
        sys.exit(
            "Required packages not found in this interpreter: websockets, httpx.\n"
            "Run:  cd Implementation && make install\n"
            "Run:  cd Implementation3 && make install\n"
            "Then: python compare_benchmark.py"
        )

    drivers: list[ImplDriver] = [CRDTDriver(), OTDriver(), PubSubSSEDriver()]
    procs: list[subprocess.Popen] = []

    if args.impl1_url:
        drivers[0].configure_remote(args.impl1_url)
    if args.impl2_url:
        drivers[1].configure_remote(args.impl2_url)
    if args.impl3_url:
        drivers[2].configure_remote(args.impl3_url)

    print("Preparing benchmark targets...")
    try:
        for d in drivers:
            if hasattr(d, "_http_base"):
                print(f"  {d.name}  remote target: {d.http_base()}")
                continue
            print(f"  {d.name}  local server on port {d.port}")
            procs.append(start_server(d))
        print("  Targets ready.")
        print()

        results_http: list[dict] = []
        results_lat:  list[dict] = []
        results_tput: list[float] = []

        for d in drivers:
            print(f"Benchmarking {d.name}...")
            print(f"  target: {d.http_base()}")
            print("  HTTP latency...", end=" ", flush=True)
            http_ms = http_latency_samples(d.http_base(), n=40)
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
