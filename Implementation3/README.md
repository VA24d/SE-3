# SyncSpace — Implementation 3 (Architecture analysis)

**Purpose:** A third end-to-end prototype for **Project 3 — Architecture analysis**, by **swapping a core integration pattern** while keeping the same **Yjs + CodeMirror** collaboration model.

| | Implementation 1 | Implementation 3 (this folder) |
|---|------------------|--------------------------------|
| **Integration pattern (documented in Task 3)** | **Mediator** — one WebSocket per client; the server forwards bytes between open sockets (star topology, duplex) | **Publish–Subscribe** — clients `POST` JSON envelopes; the server fans out to all **other** subscribers over **Server-Sent Events (SSE)** |
| **Transport** | WebSocket (binary + JSON) | HTTP POST (publish) + GET stream (subscribe) |
| **Server role** | Stateless relay; opaque CRDT bytes | Session **topic broker** (in-memory queue per connection id) |
| **Default port** | 8080 | **8082** |

`Implementation2/` in this repo is the **OT + central sequencer** comparison. Together, the three builds support comparing **mediated duplex relay**, **authoritative OT**, and **pub-sub + SSE**.

## Run

```bash
cd Implementation3
make install
make start
```

Open [http://127.0.0.1:8082/](http://127.0.0.1:8082/) (or the printed URL). **Do not** run Implementation 1 on the same port; use 8080 vs 8082 side by side for demos.

**Windows (PowerShell):** `.\start.ps1` after venv + `pip install -r requirements.txt`

## Test

```bash
make test-smoke
```

## See also

- `doc/arch/pattern-swap-impl3.md` — short rationale and trade-offs for the report.
