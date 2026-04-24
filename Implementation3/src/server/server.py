"""
SyncSpace — Implementation 3: Publish-Subscribe + SSE (Architecture Analysis).

Pattern swap vs Implementation 1 (Mediator / WebSocket star):
  - Impl 1: one bidirectional WebSocket per client; the relay "mediates" by forwarding
    frames between sockets (classic Mediator-style star topology over a duplex channel).
  - Impl 3: clients PUBLISH updates via HTTP POST; they SUBSCRIBE to peer updates via
    Server-Sent Events (SSE). The server is a topic broker / event bus per session —
    request/response + one-way push instead of a persistent WebSocket.

Same Yjs CRDT + awareness semantics on the wire (JSON envelopes with base64 payloads).

Environment: SYNCSPACE_PUBSUB_HOST (default 127.0.0.1), SYNCSPACE_PUBSUB_PORT (default 8082).
"""
import asyncio
import json
import logging
import os
import socket
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

_CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# session_id -> list of (connection_id, queue) for SSE subscribers
subscribers: dict[str, list[tuple[str, asyncio.Queue[str]]]] = {}
session_locks: dict[str, asyncio.Lock] = defaultdict(lambda: asyncio.Lock())


def _get_lan_ip() -> str:
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        if s is not None:
            s.close()


def _build_share_url(session_id: str) -> str:
    base = (os.environ.get("SYNCSPACE_PUBLIC_BASE") or "").strip().rstrip("/")
    if base:
        return f"{base}/app/?session={session_id}"
    port = int(os.environ.get("SYNCSPACE_PUBSUB_PORT", "8082"))
    public_host = (os.environ.get("SYNCSPACE_PUBLIC_HOST") or "").strip()
    if not public_host:
        public_host = _get_lan_ip()
    return f"http://{public_host}:{port}/app/?session={session_id}"


app.mount("/app", StaticFiles(directory=str(_CLIENT_DIR), html=True), name="client")


@app.get("/")
async def root():
    new_session = str(uuid.uuid4())[:8]
    return RedirectResponse(url=f"/app/?session={new_session}")


@app.get("/api/share-link")
async def share_link(session: str = ""):
    if not session:
        return {"url": ""}
    return {"url": _build_share_url(session)}


async def _register(session_id: str, connection_id: str) -> asyncio.Queue[str]:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=512)
    async with session_locks[session_id]:
        subscribers.setdefault(session_id, []).append((connection_id, q))
    logger.info(
        "SSE subscriber joined session %s (conn=%s). Peers: %d",
        session_id,
        connection_id[:8],
        len(subscribers[session_id]),
    )
    return q


async def _unregister(session_id: str, connection_id: str) -> None:
    async with session_locks[session_id]:
        if session_id not in subscribers:
            return
        subs = subscribers[session_id]
        subscribers[session_id] = [x for x in subs if x[0] != connection_id]
        if not subscribers[session_id]:
            del subscribers[session_id]
    logger.info("SSE subscriber left session %s (conn=%s)", session_id, connection_id[:8])


@app.get("/api/sessions/{session_id}/stream")
async def sse_stream(
    session_id: str,
    connection_id: str = Query(..., min_length=4, description="Per-tab id for fan-out exclude"),
    client_id: int = Query(0, description="Yjs client id (logging only)"),
):
    """
    Subscribe to session events (Server-Sent Events).
    Each browser tab should use a unique connection_id (UUID).
    """

    async def gen():
        q = await _register(session_id, connection_id)
        try:
            while True:
                payload = await q.get()
                yield f"data: {payload}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            await _unregister(session_id, connection_id)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@app.post("/api/sessions/{session_id}/publish")
async def publish(session_id: str, body: dict[str, Any]):
    """
    Publish an envelope to every other subscriber in the session (pub-sub fan-out).
    """
    from_conn = body.get("from_connection")
    envelope = body.get("envelope")
    if not from_conn or not isinstance(from_conn, str):
        raise HTTPException(400, "from_connection (str) required")
    if envelope is None:
        raise HTTPException(400, "envelope required")

    line = json.dumps(envelope, separators=(",", ":"))
    async with session_locks[session_id]:
        subs = list(subscribers.get(session_id, []))
    delivered = 0
    for conn_id, q in subs:
        if conn_id == from_conn:
            continue
        try:
            q.put_nowait(line)
            delivered += 1
        except asyncio.QueueFull:
            logger.warning("Subscriber queue full; dropping for session %s", session_id)
    return {"ok": True, "delivered": delivered}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("SYNCSPACE_PUBSUB_HOST", "127.0.0.1")
    port = int(os.environ.get("SYNCSPACE_PUBSUB_PORT", "8082"))
    uvicorn.run(app, host=host, port=port)
