"""
SyncSpace relay: HTTP entry (redirect + static client) and WebSocket broadcast per session.

Run from this directory so StaticFiles resolves ../client. See repository README.md.
Environment: SYNCSPACE_HOST (default 127.0.0.1), SYNCSPACE_PORT (default 8080). start.sh sets HOST=0.0.0.0 for LAN.
"""
import logging
import os
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

# Mount the static client files
app.mount("/app", StaticFiles(directory="../client", html=True), name="client")

@app.get("/")
async def root():
    # Redirect to a new random session
    new_session = str(uuid.uuid4())[:8]
    return RedirectResponse(url=f"/app/?session={new_session}")

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

                # Broadcast to peers
                for client in sessions[session_id]:
                    if client != websocket:
                        try:
                            if message_type == "bytes":
                                await client.send_bytes(data)
                            elif message_type == "text":
                                await client.send_text(data)
                        except Exception as e:
                            logger.error(f"Error sending to peer: {e}")
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
