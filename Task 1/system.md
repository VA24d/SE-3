# Subsystem Overview

SyncSpace is decomposed into **five main subsystems**. Each subsystem has clear boundaries and communicates with others through well-defined interfaces.

---

## 1. Editor Frontend Subsystem

**Role:** Provides the user-facing code editing interface and renders all visual collaboration elements.

**Functionality:**
- Hosts the code editor component (CodeMirror / Monaco) with syntax highlighting, line numbers, and standard editor features
- Renders remote users' cursors and selections as colored overlays
- Displays the participant list and connection status indicator
- Provides UI controls for creating/joining sessions (session ID input, share link button)
- Captures local edit operations and forwards them to the CRDT Engine

**Key Technologies:** HTML/CSS/JavaScript, CodeMirror 6 (or Monaco Editor)

**Interfaces:**
- → CRDT Engine: passes local edit operations, receives remote operations for rendering
- → Awareness Module: sends local cursor position, receives remote cursor data
- → WebSocket Client: indirectly via the CRDT engine's network provider

---

## 2. CRDT Engine Subsystem

**Role:** Manages the shared document state using Conflict-free Replicated Data Types to guarantee eventual consistency across all connected clients.

**Functionality:**
- Maintains a local Yjs `Y.Doc` replica of the shared document
- Applies local edits instantly to the replica (local-first, no network wait)
- Merges incoming remote edits automatically using CRDT merge semantics
- Guarantees that all replicas converge to an identical state regardless of edit order or timing
- Encodes incremental updates as compact binary state vectors for efficient network transfer

**Key Technologies:** Yjs (CRDT library)

**Interfaces:**
- ← Editor Frontend: receives local edit events
- → Editor Frontend: emits remote update events for re-rendering
- ↔ Communication Subsystem: sends/receives CRDT update vectors over the WebSocket channel

**Architectural Significance:** This is the core subsystem that fulfills FR-CE-01 (local-first editing), FR-CE-03 (conflict resolution), and NFR-R-01 (100% convergence guarantee). The choice of CRDT over Operational Transformation is driven by this subsystem.

---

## 3. Communication Subsystem (WebSocket Layer)

**Role:** Provides the real-time bidirectional transport layer between clients and the relay server.

**Functionality:**
- Establishes and maintains a persistent WebSocket connection (WSS) between each client and the relay server
- Transmits CRDT update vectors from the local client to the server for broadcast
- Receives CRDT updates from other clients (relayed by the server) and delivers them to the CRDT Engine
- Transmits and receives awareness data (cursor positions, user info) on a separate logical channel
- Implements heartbeat/ping-pong for connection health monitoring
- Handles automatic reconnection with exponential backoff on connection loss

**Key Technologies:** WebSocket API (browser-side), `ws` library (server-side), `y-websocket` (Yjs WebSocket provider)

**Interfaces:**
- ↔ CRDT Engine: transports CRDT update vectors
- ↔ Awareness Module: transports cursor/presence data
- ↔ Relay Server: the network endpoint

**Architectural Significance:** This subsystem directly addresses NFR-P-01 (≤ 1s E2E latency) by using persistent WebSocket connections instead of HTTP polling. It also enables NFR-R-02 (reconnection ≤ 5s) through incremental state-vector-based resynchronization.

---

## 4. Relay Server Subsystem

**Role:** Acts as a lightweight, stateless message router that forwards CRDT updates and awareness data between connected clients within a session.

**Functionality:**
- Accepts WebSocket connections from clients and groups them by session ID
- Forwards (broadcasts) CRDT update vectors from any client to all other clients in the same session
- Forwards awareness protocol messages for cursor/presence synchronization
- Maintains minimal session state: connected client list and the latest CRDT document state for new-joiner sync
- Manages session lifecycle: creation (when first client connects), teardown (when last client disconnects after a timeout period)

**Key Technologies:** Node.js, `ws` library, `y-websocket` server utility

**Interfaces:**
- ↔ Communication Subsystem (each client): WebSocket connections
- Internally: session registry (in-memory map of session ID → connected clients)

**Architectural Significance:** The relay is intentionally **stateless** in terms of edit logic — it does not interpret, transform, or resolve edits. All conflict resolution happens at the CRDT layer on each client. This design avoids a central bottleneck and keeps the server simple.

---

## 5. Awareness / Presence Subsystem

**Role:** Tracks and broadcasts ephemeral collaboration state — specifically, each user's cursor position, text selection, display name, and online status.

**Functionality:**
- Each client publishes its local cursor position and selection range whenever they change
- The subsystem broadcasts this data to all peers via the relay (using Yjs Awareness protocol)
- Remote awareness states are rendered as colored cursor markers and selection highlights in the editor
- Detects user timeout/disconnection and removes stale awareness entries

**Key Technologies:** Yjs Awareness Protocol (built into `y-websocket`)

**Interfaces:**
- → Editor Frontend: provides remote cursor/selection data for rendering
- ← Editor Frontend: receives local cursor/selection changes
- ↔ Communication Subsystem: awareness data travels on the same WebSocket but as a logically separate channel

**Architectural Significance:** This subsystem is architecturally notable because it requires a **separate data model** from the document CRDT. Awareness data is ephemeral (not persisted, not conflict-resolved) and uses a distinct protocol from the document updates, justifying its separation as an independent subsystem.

---

## Subsystem Interaction Diagram

```
┌──────────────────────────────────────────────────────┐
│                     CLIENT                           │
│                                                      │
│  ┌──────────────┐    edits    ┌──────────────┐       │
│  │   Editor     │◄──────────► │  CRDT Engine │       │
│  │  Frontend    │   updates   │   (Yjs)      │       │
│  └──────┬───────┘             └──────┬───────┘       │
│         │ cursor                     │ CRDT vectors  │
│         ▼                            ▼               │
│  ┌──────────────┐             ┌──────────────┐       │
│  │  Awareness   │◄───────────►│  WebSocket   │       │
│  │  Module      │  awareness  │  Client      │       │
│  └──────────────┘   data      └──────┬───────┘       │
│                                      │               │
└──────────────────────────────────────┼───────────────┘
                                       │ WSS
                              ┌────────▼────────┐
                              │  Relay Server   │
                              │  (Node.js)      │
                              │  - broadcast    │
                              │  - session mgmt │
                              └────────┬────────┘
                                       │ WSS
                    ┌──────────────────┼──────────────────┐
                    ▼                                     ▼
              ┌───────────┐                        ┌───────────┐
              │ Client B  │                        │ Client C  │
              └───────────┘                        └───────────┘
```