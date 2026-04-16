# Implementation Patterns

The following two design patterns are used in SyncSpace's architecture. Each pattern description includes its role, how it maps to the system's subsystems, and a diagram.

---

## Pattern 1: Observer Pattern (Publish-Subscribe)

### Role in Architecture

The Observer pattern is the primary integration mechanism between subsystems in SyncSpace. Rather than subsystems calling each other directly, they communicate through event-based publish-subscribe channels. This decouples the producer of data (e.g., the CRDT engine detecting a remote update) from the consumer (e.g., the editor frontend that needs to re-render).

### Where It Appears

1. **CRDT Engine → Editor Frontend:** When a remote update is received and merged into the local `Y.Doc`, the Yjs library fires an `observe` event on the shared text type. The editor frontend subscribes to this event and updates the CodeMirror document accordingly.

2. **Awareness Module → Editor Frontend:** When a remote user's cursor position changes, the Awareness protocol fires an `change` event. The editor listens and re-renders the cursor overlay.

3. **WebSocket Client → CRDT Engine:** When the WebSocket receives a binary message, it emits an event that the Yjs provider consumes to apply the update to the local document.

### Benefits

- **Loose coupling:** The CRDT engine does not know about the editor. It just publishes events. Any number of subscribers can listen.
- **Extensibility:** Adding new features (e.g., a change log panel) requires only adding a new subscriber, not modifying existing code.
- **Testability:** Each subsystem can be tested in isolation by mocking the events it subscribes to.

### Class Diagram

```
┌─────────────────────────────────┐
│       Y.Doc (Observable)        │
│─────────────────────────────────│
│ - sharedText: Y.Text            │
│─────────────────────────────────│
│ + on(event, callback)           │
│ + off(event, callback)          │
│ + emit(event, data)             │
└──────────┬──────────────────────┘
           │ notifies
           │
     ┌─────┴──────────────────┐
     │                        │
     ▼                        ▼
┌────────────────┐   ┌────────────────────┐
│ EditorBinding  │   │ ChangeLogPanel     │
│ (Observer)     │   │ (Observer)         │
│────────────────│   │────────────────────│
│ + update(data) │   │ + update(data)     │
│   → re-render  │   │   → append to log  │
│     CodeMirror │   │                    │
└────────────────┘   └────────────────────┘
```

### Sequence Diagram — Remote Edit Propagation

```
  WebSocket         Yjs Provider       Y.Doc          EditorBinding      CodeMirror
     │                   │               │                 │                 │
     │─ binary msg ─────►│               │                 │                 │
     │                   │─ applyUpdate ►│                 │                 │
     │                   │               │── observe ─────►│                 │
     │                   │               │   event         │─ dispatch ─────►│
     │                   │               │                 │  transaction    │
     │                   │               │                 │                 │── render
     │                   │               │                 │                 │
```

---

## Pattern 2: Mediator Pattern (Relay Server as Mediator)

### Role in Architecture

The Mediator pattern centralizes communication coordination. Instead of clients communicating directly with each other (which would require each client to know about every other client, creating an O(n²) mesh), all communication flows through a central mediator — the relay server. The relay manages session membership and handles message distribution.

### Where It Appears

The **Relay Server** acts as the mediator between all connected clients in a session:

- It maintains a registry of active sessions and their connected clients.
- When Client A sends a CRDT update, the relay distributes it to Clients B and C (and any others in the session).
- Clients never communicate directly with each other. They only know about the relay endpoint.

This is a classic star topology with the relay at the center.

### Benefits

- **Simplified client logic:** Each client only manages one WebSocket connection (to the relay), not N-1 connections to every other peer.
- **Centralized session management:** The relay can track who is connected, enforce connection limits, and handle join/leave events.
- **NAT/firewall friendly:** Browser clients behind NATs can all reach the relay server without needing peer-to-peer NAT traversal (STUN/TURN).

### Trade-offs vs. Peer-to-Peer

| Aspect | Mediator (Relay) | Direct P2P (WebRTC) |
|--------|-------------------|----------------------|
| Connections per client | 1 | N-1 |
| NAT traversal needed | No | Yes (STUN/TURN) |
| Single point of failure | Yes (relay) | No |
| Implementation complexity | Low | High |
| Latency | Client→Relay→Client | Client→Client (lower) |

For our prototype (≤ 3 users, semester timeline), the mediator's simplicity far outweighs the slight latency increase.

### Component Diagram

```
                        ┌──────────────────────────┐
                        │     Relay Server         │
                        │     (Mediator)           │
                        │──────────────────────────│
                        │ - sessions: Map<ID,      │
                        │     Set<WebSocket>>      │
                        │──────────────────────────│
                        │ + onConnection(ws, req)  │
                        │ + broadcast(sessionId,   │
                        │     message, sender)     │
                        │ + removeClient(ws)       │
                        └─────┬──────┬──────┬──────┘
                              │      │      │
                    WSS ──────┘      │      └────── WSS
                              WSS ───┘
                    ┌──────┐  ┌──────┐  ┌──────┐
                    │ A    │  │ B    │  │ C    │
                    │Client│  │Client│  │Client│
                    └──────┘  └──────┘  └──────┘

        ─── Clients never communicate directly ───
        ─── All messages flow through the Mediator ───
```

### Sequence Diagram — Mediated Broadcast

```
  Client A          Relay (Mediator)         Client B         Client C
     │                    │                     │                 │
     │── CRDT update ────►│                     │                 │
     │                    │── broadcast ───────►│                 │
     │                    │── broadcast ────────────────────────►│
     │                    │                     │                 │
     │                    │◄── awareness ───────│                 │
     │◄── broadcast ──────│                     │                 │
     │                    │── broadcast ────────────────────────►│
     │                    │                     │                 │
```
