# Stakeholder Identification (IEEE 42010)

## 1. Stakeholders

| ID    | Stakeholder           | Description                                                                                      |
|-------|-----------------------|--------------------------------------------------------------------------------------------------|
| SH-01 | End Users (Developers)    | Software developers and students who use SyncSpace to collaboratively edit code in real time.    |
| SH-02 | Development Team (team 33)| The team of developers building and maintaining SyncSpace.                                      |
| SH-03 | System Administrator      | The person responsible for deploying and operating the relay server infrastructure.              |

---

## 2. Stakeholder Concerns

| Concern ID | Concern                          | Description                                                                                   | Stakeholders  |
|------------|----------------------------------|-----------------------------------------------------------------------------------------------|---------------|
| C-01       | Real-time responsiveness         | Edits must propagate to all collaborators with low latency (≤ 1 second) so the experience feels "live." | SH-01         |
| C-02       | Data consistency                 | All users must eventually see the exact same document state, with no silent data loss from concurrent edits. | SH-01, SH-02  |
| C-03       | Ease of use                      | A new user should open the app, get a session, share a link, and start editing quickly, with optional syntax mode (Python, C++, Java) and a readable display name. | SH-01         |
| C-04       | Fault tolerance                  | The system should tolerate temporary network loss: local editing continues where possible, and peers can help resync after reconnect. | SH-01, SH-04  |
| C-05       | Architectural clarity            | The system architecture must be well-documented, follow established patterns, and demonstrate clear design rationale. | SH-02, SH-03  |
| C-06       | Maintainability and testability  | The codebase must be modular with clean subsystem boundaries so it is easy to extend, debug, and test. | SH-03         |
| C-07       | Deployment simplicity            | The relay must be easy to run (venv + one command or Makefile target) with minimal infrastructure dependencies. | SH-04         |
| C-08       | Security                         | Session access relies on unlisted capability URLs (short random session ids); production hardening would add TLS (HTTPS/WSS) and stricter controls. | SH-01, SH-04  |

---

## 3. Architecture Viewpoints

Following IEEE 42010, we define the following viewpoints to frame the stakeholder concerns:

### Viewpoint 1: Functional Viewpoint

- **Framed Concerns:** C-01 (responsiveness), C-02 (consistency), C-03 (ease of use)
- **Stakeholders:** SH-01, SH-02
- **Conventions:** Shows the system's functional decomposition — what each subsystem does, how data flows between them, and the key interfaces. Uses component diagrams and data flow descriptions.

### Viewpoint 2: Development Viewpoint

- **Framed Concerns:** C-05 (architectural clarity), C-06 (maintainability)
- **Stakeholders:** SH-02, SH-03
- **Conventions:** Shows the module/package structure, technology choices, and dependency relationships. Uses package diagrams and dependency tables.

### Viewpoint 3: Deployment Viewpoint

- **Framed Concerns:** C-07 (deployment simplicity), C-08 (security)
- **Stakeholders:** SH-04, SH-03
- **Conventions:** Shows the runtime infrastructure — where components run, how they communicate over the network, and security boundaries. Uses deployment diagrams.

### Viewpoint 4: Reliability Viewpoint

- **Framed Concerns:** C-02 (consistency), C-04 (fault tolerance)
- **Stakeholders:** SH-01, SH-04
- **Conventions:** Shows failure modes, recovery mechanisms, and the consistency guarantees provided by the CRDT layer. Uses scenario descriptions and failure-mode tables.

---

## 4. Architecture Views

### View 1: Functional View (governs: Functional Viewpoint)

**Concerns addressed:** C-01, C-02, C-03

The system is decomposed into **per-browser** editor, CRDT, and WebSocket client layers, plus a **shared relay**, as follows:

```
   User A's Browser                                User B's Browser
  ┌─────────────────┐                             ┌─────────────────┐
  │ Editor Frontend │                             │ Editor Frontend │
  │  (CodeMirror)   │                             │  (CodeMirror)   │
  └────────┬────────┘                             └────────┬────────┘
           │ local edits                                    │
  ┌────────▼────────┐                             ┌────────▼────────┐
  │  CRDT Engine    │                             │  CRDT Engine    │
  │  (Yjs Y.Doc)    │                             │  (Yjs Y.Doc)    │
  └────────┬────────┘                             └────────┬────────┘
           │ framed WS messages (doc + awareness)           │
  ┌────────▼────────┐                             ┌────────▼────────┐
  │  WebSocket      │◄──────── WebSocket ────────►│  WebSocket      │
  │  (custom client)│         Relay               │  (custom client)│
  └─────────────────┘     ┌──────────┐            └─────────────────┘
                          │  Relay   │
                          │ (FastAPI)│
                          └──────────┘
```

- **Responsiveness (C-01):** Edits are applied locally first, then broadcast asynchronously. The user does not wait for the network for local typing.
- **Consistency (C-02):** The Yjs CRDT guarantees that all replicas converge to the same state given the same set of updates; the relay forwards opaque bytes and does not interpret document content.
- **Ease of use (C-03):** Visiting `/` redirects to `/app/?session=…` with a new short session id. **Share Link** calls `/api/share-link` so the copied URL uses a LAN-routable host (or `SYNCSPACE_PUBLIC_BASE` / `SYNCSPACE_PUBLIC_HOST` when set). The sidebar supports syntax highlighting mode and display name.

### View 2: Development View (governs: Development Viewpoint)

**Concerns addressed:** C-05, C-06

The prototype is organized as a thin **Python** relay and a **static ES-module** client (no separate `y-websocket` dependency on either side). Logical responsibilities map to paths as follows:

| Area (logical)        | Location (repository)              | Technology                         | Responsibility |
|-----------------------|------------------------------------|------------------------------------|----------------|
| Editor UI             | `Implementation/src/client/` (`index.html`, `style.css`, `app.js`) | CodeMirror 6, HTML/CSS, ES modules | Editing UX, language mode, share button, participant list |
| CRDT + collaboration  | `Implementation/src/client/app.js` | Yjs, `y-codemirror.next`, `y-protocols/awareness` | Shared text, cursors, undo |
| WebSocket client      | `Implementation/src/client/app.js` (`SimpleProvider`) | Native `WebSocket`, prefixed binary + JSON control | Join handshake (`request_state`), doc/awareness frames |
| Relay server          | `Implementation/src/server/server.py` | FastAPI, Uvicorn, Starlette WebSocket | HTTP redirect, static `/app`, `/api/share-link`, `/ws/{session_id}` broadcast |
| Automated checks      | `Implementation/tests/`            | Python (`ws_relay_smoke`, `benchmark_nfr`) | Smoke relay, sample latency/throughput |

The client talks to Yjs through stable library APIs; the wire format to the relay is a small, project-specific framing layer (see ADR 2, ADR 5, ADR 8).

### View 3: Deployment View (governs: Deployment Viewpoint)

**Concerns addressed:** C-07, C-08

```
┌─────────────────────────────────────────────┐
│         Host (laptop, VM, or server)         │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  Relay (Python: Uvicorn + FastAPI)      │  │
│  │  - Default port 8080 (SYNCSPACE_PORT)   │  │
│  │  - SYNCSPACE_HOST (e.g. 0.0.0.0 LAN)    │  │
│  │  - Static client at /app                │  │
│  │  - WebSocket at /ws/{session_id}       │  │
│  │  - Start: Makefile / start.sh / uvicorn │  │
│  └────────────────────────────────────────┘  │
│                                              │
└──────────────────┬───────────────────────────┘
                   │  WS / WSS (TLS in production)
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   Browser A  Browser B  Browser C
   (/app/     (/app/     (/app/
    ES modules) ES modules) ES modules)
```

- **Deployment simplicity (C-07):** From `Implementation/`, create a venv, `pip install -r requirements.txt`, then `make start` (or `start.sh` / `start.ps1`). The same process serves static assets and the WebSocket relay.
- **Security (C-08):** Sessions are capability URLs (short ids from `uuid4` on the server). Local and LAN demos typically use `http`/`ws`; a production deployment should terminate TLS and use `https`/`wss`, and may set `SYNCSPACE_PUBLIC_BASE` for stable share links behind a reverse proxy.

### View 4: Reliability View (governs: Reliability Viewpoint)

**Concerns addressed:** C-02, C-04

| Failure Scenario          | System response (as implemented)                                                                 | Notes |
|---------------------------|---------------------------------------------------------------------------------------------------|-------|
| Client loses WebSocket    | UI shows disconnected; after ~5s the page reloads to reconnect. Local Yjs state survives until reload. | Not a silent in-band reconnect loop; recovery is reload-oriented. |
| Client reconnects         | New WebSocket to `/ws/{session}`; join sends `request_state`; peers may respond with `Y.encodeStateAsUpdate` and awareness. | Full sync depends on at least one peer still holding state. |
| Concurrent edits          | Yjs merge is deterministic; all replicas that receive the same updates converge.                 | Matches CRDT expectation. |
| Relay process restarts    | All sockets drop; clients follow the same reload/rejoin path. In-memory sessions are empty until clients return. | No server-side persistence (see ADR 7). |
| Sole peer leaves          | If no peer remains, document state is not recoverable from the relay alone.                      | Acceptable for ephemeral MVP sessions. |

The CRDT layer still provides the core guarantee that **concurrent edits do not corrupt the document**; the prototype prioritizes a small relay over durable server-side history or seamless long-lived WebSocket sessions without reload.
