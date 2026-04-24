"""
SyncSpace-OT relay: Operational Transformation + Central Sequencer.

Architecture contrast with Implementation 1 (CRDT + stateless relay):
  - The server IS the document authority: it stores the full text in memory.
  - Every client op is transformed by the server against concurrent ops before
    being applied and broadcast. No client can modify the document without
    server confirmation.
  - Wire protocol: JSON text only (no binary framing).

Environment: SYNCSPACE_OT_HOST (default 127.0.0.1), SYNCSPACE_OT_PORT (default 8081).
"""
import asyncio
import json
import logging
import os
import socket
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


# ── OT transform & apply ──────────────────────────────────────────────────────

def _transform_op(op1: dict, op2: dict) -> Optional[dict]:
    """
    Transform op1 assuming op2 was already applied to the document.
    Returns the adjusted op1, or None if op1 becomes a no-op.

    This is the core of Operational Transformation: the server must call
    this for every client op against every concurrent server op in its history.
    Unlike CRDT, this computation runs on the server on every message.
    """
    t1, t2 = op1["type"], op2["type"]

    if t1 == "insert":
        pos1 = op1["pos"]
        if t2 == "insert":
            pos2 = op2["pos"]
            if pos2 <= pos1:
                return {**op1, "pos": pos1 + len(op2["text"])}
            return op1
        elif t2 == "delete":
            pos2, len2 = op2["pos"], op2["length"]
            if pos2 + len2 <= pos1:
                return {**op1, "pos": pos1 - len2}
            if pos2 < pos1:
                return {**op1, "pos": pos2}
            return op1

    elif t1 == "delete":
        pos1, len1 = op1["pos"], op1["length"]
        if t2 == "insert":
            pos2 = op2["pos"]
            if pos2 <= pos1:
                return {**op1, "pos": pos1 + len(op2["text"])}
            if pos2 < pos1 + len1:
                return {**op1, "length": len1 + len(op2["text"])}
            return op1
        elif t2 == "delete":
            pos2, len2 = op2["pos"], op2["length"]
            end1, end2 = pos1 + len1, pos2 + len2
            if end2 <= pos1:
                return {**op1, "pos": pos1 - len2}
            if pos2 >= end1:
                return op1
            # Overlapping deletions — shrink op1 by the overlap.
            if pos2 <= pos1 and end2 >= end1:
                return None  # fully consumed by op2
            if pos2 <= pos1:
                kept = end1 - end2
                return {**op1, "pos": pos2, "length": max(0, kept)}
            kept = len1 - (min(end1, end2) - pos2)
            return {**op1, "length": max(0, kept)} if kept > 0 else None

    return op1


def _apply_op(doc: str, op: dict) -> str:
    """Apply one insert or delete op to the authoritative document string."""
    if op["type"] == "insert":
        p = max(0, min(op["pos"], len(doc)))
        return doc[:p] + op["text"] + doc[p:]
    if op["type"] == "delete":
        p = max(0, min(op["pos"], len(doc)))
        e = max(p, min(p + op["length"], len(doc)))
        return doc[:p] + doc[e:]
    return doc


# ── Session state ─────────────────────────────────────────────────────────────

@dataclass
class ClientInfo:
    ws: WebSocket
    client_id: str
    name: str
    color: str
    cursor_pos: int = 0


@dataclass
class Session:
    doc: str = ""
    revision: int = 0
    # history[i] = (revision_number, [ops]) — needed to transform late-arriving ops.
    history: list = field(default_factory=list)
    clients: dict = field(default_factory=dict)  # client_id → ClientInfo
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_sessions: dict[str, Session] = {}

_COLORS = ["#f87171", "#fb923c", "#fbbf24", "#34d399",
           "#38bdf8", "#818cf8", "#a78bfa", "#f472b6"]


def _get_session(sid: str) -> Session:
    if sid not in _sessions:
        _sessions[sid] = Session()
    return _sessions[sid]


# ── Utilities ─────────────────────────────────────────────────────────────────

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
        if s:
            s.close()


def _build_share_url(session_id: str) -> str:
    base = (os.environ.get("SYNCSPACE_OT_PUBLIC_BASE") or "").strip().rstrip("/")
    if base:
        return f"{base}/app/?session={session_id}"
    port = int(os.environ.get("SYNCSPACE_OT_PORT", "8081"))
    host = (os.environ.get("SYNCSPACE_OT_PUBLIC_HOST") or "").strip() or _get_lan_ip()
    return f"http://{host}:{port}/app/?session={session_id}"


# ── HTTP & static ─────────────────────────────────────────────────────────────

app.mount("/app", StaticFiles(directory="../client", html=True), name="client")


@app.get("/")
async def root():
    new_session = str(uuid.uuid4())[:8]
    return RedirectResponse(url=f"/app/?session={new_session}")


@app.get("/api/share-link")
async def share_link(session: str = ""):
    if not session:
        return {"url": ""}
    return {"url": _build_share_url(session)}


# ── WebSocket broadcast helper ────────────────────────────────────────────────

async def _broadcast(session: Session, skip_id: str, msg: dict) -> None:
    text = json.dumps(msg)
    dead = []
    for cid, info in session.clients.items():
        if cid == skip_id:
            continue
        try:
            await info.ws.send_text(text)
        except Exception:
            dead.append(cid)
    for cid in dead:
        session.clients.pop(cid, None)


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = _get_session(session_id)
    client_id = str(uuid.uuid4())[:8]
    color = _COLORS[hash(client_id) % len(_COLORS)]
    name = f"User_{client_id[:4]}"
    info = ClientInfo(ws=websocket, client_id=client_id, name=name, color=color)

    async with session.lock:
        session.clients[client_id] = info
        # Send the authoritative document state to the new client.
        # This is the key difference from Implementation 1: the server holds
        # the document, so new clients get it from the server — not from peers.
        await websocket.send_text(json.dumps({
            "type": "init",
            "rev": session.revision,
            "doc": session.doc,
            "client_id": client_id,
            "color": color,
            "clients": [
                {"client_id": cid, "name": c.name,
                 "color": c.color, "cursor_pos": c.cursor_pos}
                for cid, c in session.clients.items() if cid != client_id
            ],
        }))
        await _broadcast(session, client_id, {
            "type": "join", "client_id": client_id, "name": name, "color": color,
        })

    logger.info("Client %s joined session %s", client_id, session_id)

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "op":
                client_rev = int(msg.get("rev", session.revision))
                incoming_ops = [o for o in msg.get("ops", []) if o]

                async with session.lock:
                    # ── Core OT step ─────────────────────────────────────────
                    # Transform client ops against every server op applied since
                    # the client's revision. This is O(history_depth × ops_per_msg)
                    # and runs on every message — the fundamental cost of OT.
                    ops = list(incoming_ops)
                    for _rev, hist_ops in session.history[client_rev:]:
                        next_ops: list = []
                        for op in ops:
                            cur = op
                            for hop in hist_ops:
                                if cur is None:
                                    break
                                cur = _transform_op(cur, hop)
                            if cur is not None:
                                next_ops.append(cur)
                        ops = next_ops

                    # Apply the now-canonical ops to the authoritative document.
                    for op in ops:
                        session.doc = _apply_op(session.doc, op)

                    if ops:
                        session.revision += 1
                        new_rev = session.revision
                        session.history.append((new_rev, ops))
                    else:
                        new_rev = session.revision

                    # Acknowledge to the originating client.
                    await websocket.send_text(json.dumps({"type": "ack", "rev": new_rev}))

                    if ops:
                        # Broadcast the transformed (canonical) ops to all peers.
                        await _broadcast(session, client_id, {
                            "type": "op",
                            "rev": new_rev,
                            "author": client_id,
                            "ops": ops,
                        })

            elif mtype == "rename":
                new_name = str(msg.get("name", name))[:24].strip() or name
                async with session.lock:
                    if client_id in session.clients:
                        session.clients[client_id].name = new_name
                name = new_name
                await _broadcast(session, client_id, {
                    "type": "rename", "client_id": client_id, "name": new_name,
                })

            elif mtype == "cursor":
                pos = int(msg.get("pos", 0))
                async with session.lock:
                    if client_id in session.clients:
                        session.clients[client_id].cursor_pos = pos
                await _broadcast(session, client_id, {
                    "type": "cursor", "client_id": client_id, "pos": pos,
                })

    except (WebSocketDisconnect, Exception) as exc:
        if not isinstance(exc, WebSocketDisconnect):
            logger.error("Error for client %s: %s", client_id, exc)
    finally:
        async with session.lock:
            session.clients.pop(client_id, None)
            if not session.clients:
                _sessions.pop(session_id, None)
        await _broadcast(session, client_id, {
            "type": "leave", "client_id": client_id,
        })
        logger.info("Client %s left session %s", client_id, session_id)


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("SYNCSPACE_OT_HOST", "127.0.0.1")
    port = int(os.environ.get("SYNCSPACE_OT_PORT", "8081"))
    uvicorn.run(app, host=host, port=port)
