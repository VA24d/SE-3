"""
SyncSpace relay: HTTP entry (redirect + static client) and WebSocket broadcast per session.

Run from this directory so StaticFiles resolves ../client. See repository README.md.
Environment: SYNCSPACE_HOST (default 127.0.0.1), SYNCSPACE_PORT (default 8080). start.sh sets HOST=0.0.0.0 for LAN.
Optional: SYNCSPACE_PUBLIC_BASE (e.g. https://xyz.ngrok.io) or SYNCSPACE_PUBLIC_HOST for the share link; otherwise the
server picks a routable LAN IP (UDP trick) so Share Link is not stuck on 127.0.0.1.
"""
import logging
import os
import socket
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from collections import defaultdict
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Session ID -> set of WebSockets
sessions = defaultdict(set)


def _get_lan_ip() -> str:
    """Return a non-loopback address suitable for others on the LAN; fallback 127.0.0.1."""
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
    port = int(os.environ.get("SYNCSPACE_PORT", "8080"))
    public_host = (os.environ.get("SYNCSPACE_PUBLIC_HOST") or "").strip()
    if not public_host:
        public_host = _get_lan_ip()
    return f"http://{public_host}:{port}/app/?session={session_id}"


# Mount the static client files
app.mount("/app", StaticFiles(directory="../client", html=True), name="client")

@app.get("/")
async def root():
    # Redirect to a new random session
    new_session = str(uuid.uuid4())[:8]
    return RedirectResponse(url=f"/app/?session={new_session}")


@app.get("/api/share-link")
async def share_link(session: str = ""):
    """
    Return a copy-pasteable URL with this machine's address (not localhost) and the session id.
    """
    if not session:
        return {"url": ""}
    return {"url": _build_share_url(session)}

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    sessions[session_id].add(websocket)
    logger.info(f"Client joined session {session_id}. Total clients: {len(sessions[session_id])}")

    try:
        while True:
            # We accept both text and binary messages. 
            # We broadcast them natively to all OTHER clients in the session.
            message_type = None
            try:
                # receive will wait for the next message
                message = await websocket.receive()
                if "bytes" in message:
                    message_type = "bytes"
                    data = message["bytes"]
                elif "text" in message:
                    message_type = "text"
                    data = message["text"]
                else:
                    continue

                # Broadcast to peers (collect dead peers to remove)
                dead_peers = set()
                for client in sessions[session_id]:
                    if client != websocket:
                        try:
                            if message_type == "bytes":
                                await client.send_bytes(data)
                            elif message_type == "text":
                                await client.send_text(data)
                        except Exception as e:
                            logger.error(f"Error sending to peer: {e}")
                            dead_peers.add(client)
                sessions[session_id] -= dead_peers
            except Exception as e:
                logger.error(f"Error in message loop: {e}")
                break

    except WebSocketDisconnect:
        pass
    finally:
        sessions[session_id].discard(websocket)
        logger.info(f"Client left session {session_id}. Remaining: {len(sessions[session_id])}")
        if not sessions[session_id]:
            del sessions[session_id]

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("SYNCSPACE_HOST", "127.0.0.1")
    port = int(os.environ.get("SYNCSPACE_PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
