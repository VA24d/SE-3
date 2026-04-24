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
| C-03       | Ease of use                      | A new user should be able to create or join a session and start editing within 60 seconds, with no complex setup. | SH-01         |
| C-04       | Fault tolerance                  | The system must handle temporary network disconnections gracefully, buffering edits and resyncing automatically. | SH-01, SH-04  |
| C-05       | Architectural clarity            | The system architecture must be well-documented, follow established patterns, and demonstrate clear design rationale. | SH-02, SH-03  |
| C-06       | Maintainability and testability  | The codebase must be modular with clean subsystem boundaries so it is easy to extend, debug, and test. | SH-03         |
| C-07       | Deployment simplicity            | The relay server must be easy to deploy (ideally a single command) with minimal infrastructure dependencies. | SH-04         |
| C-08       | Security                         | Session access must be controlled via unique, hard-to-guess session IDs; communication should use encrypted channels. | SH-01, SH-04  |

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

The system is decomposed into five subsystems with the following data flow:

```
   User A's Browser                                User B's Browser
  ┌─────────────────┐                             ┌─────────────────┐
  │ Editor Frontend │                            │ Editor Frontend │
  │  (CodeMirror)   │                            │  (CodeMirror)   │
  └────────┬────────┘                             └────────┬────────┘
           │ local edits                                    │
  ┌────────▼────────┐                             ┌────────▼────────┐
  │  CRDT Engine    │                             │  CRDT Engine    │
  │  (Yjs Y.Doc)    │                             │  (Yjs Y.Doc)    │
  └────────┬────────┘                             └────────┬────────┘
           │ update vectors                                 │
  ┌────────▼────────┐                             ┌────────▼────────┐
  │  WebSocket      │◄──────── WSS ──────────────►│  WebSocket      │
  │  Client         │         Relay               │  Client         │
  └─────────────────┘     ┌──────────┐            └─────────────────┘
                          │  Relay   │
                          │  Server  │
                          └──────────┘
```

- **Responsiveness (C-01):** Edits are applied locally first, then broadcast asynchronously. The user never waits for the network.
- **Consistency (C-02):** The Yjs CRDT guarantees that all replicas converge to the same state.
- **Ease of use (C-03):** Sessions are created with one click; joining requires only a session ID.

### View 2: Development View (governs: Development Viewpoint)

**Concerns addressed:** C-05, C-06

| Module / Package     | Technology           | Responsibility                         | Dependencies            |
|----------------------|----------------------|----------------------------------------|-------------------------|
| `client/editor`      | CodeMirror 6, HTML/JS | Code editor UI, cursor rendering       | `client/crdt`, `client/awareness` |
| `client/crdt`        | Yjs                  | Local CRDT replica management          | Yjs library             |
| `client/awareness`   | Yjs Awareness        | Cursor position broadcasting           | Yjs Awareness protocol  |
| `client/websocket`   | y-websocket (client) | WebSocket connection to relay          | y-websocket             |
| `server/relay`       | Node.js, ws, y-websocket (server) | WebSocket relay, session routing | ws, y-websocket    |

All subsystems communicate through well-defined Yjs APIs, ensuring loose coupling and independent testability.

### View 3: Deployment View (governs: Deployment Viewpoint)

**Concerns addressed:** C-07, C-08

```
┌─────────────────────────────────────────────┐
│              Cloud / Local Host              │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  Relay Server (Node.js process)        │  │
│  │  - Listens on port 1234 (WSS)          │  │
│  │  - Single process, in-memory sessions  │  │
│  │  - Start: `node server.js`             │  │
│  └────────────────────────────────────────┘  │
│                                              │
└──────────────────┬───────────────────────────┘
                   │  WSS (TLS in production)
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   Browser A  Browser B  Browser C
   (Static    (Static    (Static
    HTML/JS)   HTML/JS)   HTML/JS)
```

- **Deployment simplicity (C-07):** The relay server is a single Node.js process started with one command. The client is static HTML/JS served from any web server or opened locally.
- **Security (C-08):** Production deployment uses WSS (WebSocket over TLS). Session IDs are randomly generated UUIDs.

### View 4: Reliability View (governs: Reliability Viewpoint)

**Concerns addressed:** C-02, C-04

| Failure Scenario          | System Response                                                                    | Recovery Time |
|---------------------------|------------------------------------------------------------------------------------|---------------|
| Client loses network      | Edits continue locally in CRDT replica. Ops buffered in memory.                   | —             |
| Network reconnects        | WebSocket reconnects automatically. CRDT state vectors are exchanged to sync only missing operations. | ≤ 5 seconds   |
| Concurrent edits on same line | CRDT merge function deterministically resolves the conflict. All replicas converge. | Automatic     |
| Relay server restarts     | Clients detect disconnect, reconnect, and perform full state sync.                | ≤ 10 seconds  |

The CRDT convergence guarantee (NFR-R-01) ensures that **no edits are ever lost**, even after arbitrary network partitions or reordering of messages.
