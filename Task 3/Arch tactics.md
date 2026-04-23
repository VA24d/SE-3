# Architectural Tactics

The following architectural tactics are employed in SyncSpace to address specific non-functional requirements. Each tactic is a proven design technique from the software architecture literature (Bass, Clements & Kazman) applied to our collaborative editing context.

---

## Tactic 1: Local-First Optimistic Replication

**NFR Addressed:** NFR-P-02 (Local keystroke latency ≤ 16 ms), NFR-P-01 (E2E sync ≤ 1s)

**Description:** Every user edit is applied immediately to the local CRDT replica without waiting for a server round-trip. The edit is then asynchronously broadcast to peers. This means the user's typing experience is never blocked by network latency — the editor responds as if it were a purely local application.

**How it works in SyncSpace:**
1. User types a character → the edit is applied to the local `Y.Doc` (Yjs document) instantly (~1 ms).
2. The Yjs provider encodes the edit as a compact binary update vector.
3. The vector is sent to the relay server via WebSocket (asynchronous, non-blocking).
4. Remote clients receive the vector and merge it into their own replicas.

**Trade-off:** Replicas may temporarily diverge (users see different states for a brief moment). The CRDT guarantees they converge once all messages are delivered. This is an acceptable trade-off for the responsiveness gained.

---

## Tactic 2: Fast Failure Detection and Recovery (Prototype Profile)

**NFR Addressed:** NFR-R-02 (Client reconnection within a few seconds — **target** in SRS), fault visibility (FR-UI-03 area)

**Description:** The transport must detect dead connections so the UI can reflect **disconnected** state and users can recover. In the **prototype**, we rely on the **WebSocket’s built-in close semantics** and a **simple reload-based recovery** rather than a custom application heartbeat protocol.

**How it works in SyncSpace (as implemented):**
- When the socket closes, the client shows **Disconnected** and schedules a **full page reload** after a short delay (5 seconds), which re-establishes a session from the URL and re-runs the Yjs + provider bootstrap.
- **Join / catch-up:** Peers answer a JSON `request_state` message by sending a **full Yjs update** (`encodeStateAsUpdate`) so a reloaded or new tab can converge without the server storing the document.
- **Production / future work:** The SRS-style **application heartbeats** and **exponential backoff** can replace the reload stub without changing the relay’s forwarding role.

**Trade-off:** A full reload is heavier than incremental reconnect but is **simple and robust** for a semester prototype and keeps the client provider small.

---

## Tactic 3: Peer-Assisted State Catch-Up (Yjs State Encoding)

**NFR Addressed:** NFR-R-01 (100% convergence — **CRDT guarantee**), NFR-R-02 (timely resync after reconnect / new joiner)

**Description:** New or reconnecting replicas must obtain missing operations. **Yjs** can exchange **full encoded updates** or **differential** updates when peers compare state vectors. Our **relay does not participate** in that logic—it only delivers frames.

**How it works in SyncSpace (as implemented):**
1. A joiner connects and sends a JSON **`request_state`** message on the WebSocket.
2. Each existing peer responds with one or more **`0x00`-prefixed** binary messages containing **`Y.encodeStateAsUpdate(doc)`** (full snapshot from that peer’s replica; Yjs merges redundant responses safely).
3. Awareness is similarly prefixed (`0x01`) so cursors converge after document text.

**Trade-off:** Broadcast-style catch-up can send **more bytes** than a perfect server-side diff when many peers reply at once, but it preserves **ADR-004** (no document authority on the server) and stays correct for small sessions.

---

## Tactic 4: Separation of Persistent and Ephemeral State

**NFR Addressed:** NFR-P-01 (E2E sync ≤ 1s), NFR-SC-01 (3 concurrent users)

**Description:** SyncSpace separates document state (persistent, conflict-resolved via CRDT) from presence state (ephemeral, last-writer-wins). This separation ensures that cursor/presence updates — which are high-frequency and disposable — do not pollute the document CRDT history or inflate its state vector.

**How it works in SyncSpace:**
- **Document state** flows through the Yjs `Y.Doc` CRDT, which guarantees convergence and preserves full edit history.
- **Awareness state** (cursor position, user name, online status) flows through the Yjs Awareness protocol, which uses a simple last-writer-wins overwrite model with automatic expiry (30-second timeout for stale entries).
- Both channels share the same WebSocket connection but are logically independent.

**Trade-off:** Two parallel data models must be maintained and synchronized. In practice, the Yjs library handles this internally, so the implementation overhead is minimal.

---

## Tactic 5: Stateless Relay (Reduce Server Complexity)

**NFR Addressed:** NFR-R-02 (Reconnection ≤ 5s), deployment simplicity (Concern C-07)

**Description:** The relay server is intentionally kept stateless with respect to edit logic. It does not parse, validate, or transform any document operations. It merely forwards binary CRDT update vectors between clients. This minimizes server complexity and eliminates the server as a correctness bottleneck.

**How it works in SyncSpace:**
- The relay receives a binary (or text) frame from Client A on a session channel.
- It broadcasts the frame **unchanged** to all **other** clients on the same channel.
- It keeps **only** the set of open sockets per session—**no Y.Doc**, no persistence.

**Trade-off:** The relay has no ability to enforce application-level rules (e.g., "this user is read-only") because it does not inspect message content. Access control must be enforced at the connection level (allowing or rejecting the WebSocket connection) rather than at the operation level.

---

## Summary: Tactic-to-NFR Mapping

| Tactic | NFRs Addressed |
|--------|---------------|
| Local-First Optimistic Replication | NFR-P-01, NFR-P-02 |
| Fast Failure Detection and Recovery (Prototype Profile) | NFR-R-02, NFR-P-03 (targets) |
| Peer-Assisted State Catch-Up (Yjs State Encoding) | NFR-R-01, NFR-R-02 |
| Separation of Persistent/Ephemeral State | NFR-P-01, NFR-SC-01 |
| Stateless Relay | NFR-R-02, Deployment simplicity |
