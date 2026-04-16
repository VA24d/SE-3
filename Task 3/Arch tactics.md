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

## Tactic 2: Heartbeat-Based Failure Detection

**NFR Addressed:** NFR-R-02 (Client reconnection ≤ 5 seconds), NFR-P-03 (Convergence ≤ 2s)

**Description:** The system uses periodic heartbeat (ping/pong) messages between clients and the relay server to detect connection failures quickly. If a heartbeat response is not received within a configured timeout, the connection is declared dead and reconnection logic is triggered.

**How it works in SyncSpace:**
- The WebSocket layer sends a ping frame every 2 seconds.
- If no pong is received within 3 seconds, the connection is considered lost.
- The client immediately enters reconnection mode with exponential backoff (1s, 2s, 4s, capped at 10s).
- On reconnection, the client sends its CRDT state vector to the relay, and the relay responds with only the missing updates (incremental sync).

**Trade-off:** Heartbeats add a small amount of network overhead (a few bytes every 2 seconds). This is negligible compared to the benefit of fast failure detection.

---

## Tactic 3: Incremental State Synchronization (State Vector Exchange)

**NFR Addressed:** NFR-R-01 (100% convergence after partition), NFR-R-02 (Reconnection ≤ 5s)

**Description:** Instead of transferring the entire document on every reconnection or new-joiner event, SyncSpace uses Yjs state vectors — compact summaries of which operations a replica has already seen. The relay compares the client's state vector against its own and sends back only the missing operations.

**How it works in SyncSpace:**
1. Client reconnects and sends its state vector (a small binary blob, typically < 1 KB).
2. Relay computes the diff: `missingUpdates = relay.encodeStateAsUpdate(clientStateVector)`.
3. Only the missing updates are transmitted, not the full document.

**Trade-off:** The relay must maintain an in-memory copy of the latest CRDT state per session to compute diffs. This uses memory proportional to the document size, but avoids the bandwidth cost of full retransmission on every reconnect.

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
- The relay receives a binary blob from Client A on a session channel.
- It broadcasts the blob unchanged to all other clients on the same channel.
- It maintains an in-memory Yjs document per session solely for new-joiner sync — it never modifies this document based on its own logic.

**Trade-off:** The relay has no ability to enforce application-level rules (e.g., "this user is read-only") because it does not inspect message content. Access control must be enforced at the connection level (allowing or rejecting the WebSocket connection) rather than at the operation level.

---

## Summary: Tactic-to-NFR Mapping

| Tactic | NFRs Addressed |
|--------|---------------|
| Local-First Optimistic Replication | NFR-P-01, NFR-P-02 |
| Heartbeat-Based Failure Detection | NFR-R-02, NFR-P-03 |
| Incremental State Synchronization | NFR-R-01, NFR-R-02 |
| Separation of Persistent/Ephemeral State | NFR-P-01, NFR-SC-01 |
| Stateless Relay | NFR-R-02, Deployment simplicity |
