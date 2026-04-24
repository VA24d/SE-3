# Implementation 3: Pattern swap (Mediator → Publish–Subscribe)

## What we swapped

In **Task 3 / `Impl patterns.md`**, the relay is described with the **Mediator** pattern: clients do not connect to each other; they only talk to the relay, which coordinates delivery (a star with the relay at the center). **Implementation 1** realizes that with a **stateless WebSocket relay** (duplex, binary CRDT + awareness frames).

**Implementation 3** keeps the **same Yjs document and awareness semantics** on the wire, but changes the *coordination style* to **Publish–Subscribe**:

- **Publish:** `POST /api/sessions/{session_id}/publish` with `{ "from_connection", "envelope" }`.
- **Subscribe:** `GET /api/sessions/{session_id}/stream?connection_id=...` (SSE). Each tab uses a **unique `connection_id` (UUID)** so the broker can deliver to *peers* only (the publisher does not get its own event back on its SSE, mirroring the WebSocket `!= sender socket` rule).

The server holds **no Y.Doc**; it only routes envelopes — same architectural boundary as Implementation 1.

## Why this is a fair analysis lever

- **Same CRDT and editor:** differences in feel and cost come from **integration**, not from switching away from Yjs.
- **Clear contrast to Implementation 2:** Implementation 2 changes **concurrency semantics** (OT + authority). Implementation 3 keeps **CRDT** but changes **message-passing style** (HTTP pub-sub vs WebSocket mediation).

## Trade-offs (for the technical report)

| | WebSocket Mediator (Impl 1) | HTTP Pub-Sub (Impl 3) |
|---|-----------------------------|------------------------|
| Connections | One long-lived duplex socket | One **SSE** stream + many short **POST** requests |
| Ordering | Single socket naturally serializes client sends | **Per-tab** outbox in the client code serializes `fetch` to avoid Yjs op reordering |
| Caching / proxies | Some proxies mishandle long WS | SSE is one-way HTTP; POST is standard REST (easier in strict corporate proxies) — but **higher** overhead for bursty typing |
| Semantics | Familiar for real-time | Still viable for a prototype; production would add batching, back-pressure, and possibly WS again for efficiency |

## Grading note

Cite this file and the `Implementation3/` code when you extend **§5 Architecture analysis** in `Technical report.md` beyond the CRDT vs OT table.
