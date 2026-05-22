# SyncSpace: Real-Time Collaborative Code Editor
**S26CS6.401 — Software Engineering | Project 3 Proposal**

Team 33
Vijay, hardik, Aryan, 

---

## 1. Description of the Use Case

**Domain:** Education / Enterprise

Software development teams and students in remote or distributed settings routinely collaborate on code through a painful workaround: one person shares their screen while others watch passively, or changes are passed back and forth through Git commits. Neither approach supports true simultaneous editing. Existing tools like Google Docs solved this for plain text years ago, but no lightweight, purpose-built solution exists for code with syntax awareness.

SyncSpace targets software engineering teams doing pair programming, code review sessions, and technical interviews, as well as students in online lab environments collaborating on assignments. The core problem is that simultaneous edits to the same document by multiple users produce conflicts — and traditional locking mechanisms resolve this by serializing all writes through a central server, creating a single point of failure and introducing latency that makes typing feel sluggish for remote users.

The significance is high: remote software development is now the norm, not the exception. A collaborative editor that feels local — where keystrokes appear instantly regardless of network round-trip time — fundamentally changes how distributed teams write code together.

---

## 2. Key Functionalities

### Core Features

- **Conflict-Free Simultaneous Editing:** Multiple users type in the same file at the same time with no locking. The CRDT layer automatically merges all concurrent edits into a consistent document state across all clients, regardless of the order operations arrive.
- **Real-Time Cursor & Presence:** Each collaborator's cursor position and selection are broadcast via WebSocket and rendered in the editor with a unique color and name label.
- **WebSocket Sync Layer:** A lightweight sync server receives CRDT operations from one client and fans them out to all other clients on the same document session, maintaining eventual consistency.
- **Syntax-Highlighted Code Editor:** A browser-based editor (built on CodeMirror or Monaco) with language-aware syntax highlighting, providing a professional coding experience.

### User Interaction

Entirely browser-based. Users create or join a session via a shared URL — no installation required. The editor loads instantly, and collaborators appear as colored cursors in real time as they join.

### Technical Highlights

- **Yjs (CRDT library)** — battle-tested JavaScript CRDT implementation supporting rich text and code documents
- **y-websocket** — Yjs-compatible WebSocket provider handling sync, awareness, and reconnection
- **CodeMirror 6 / Monaco Editor** — browser-based code editor with native Yjs binding support
- **Node.js sync server** — stateless WebSocket relay; document state lives in the CRDT itself
- **Redis** — persists CRDT document state so sessions survive server restarts

### Architectural Tactics

- **Availability via Decentralization** — CRDT state is held client-side; server failure does not corrupt document state
- **Performance via Local Optimism** — edits are applied locally first and synced asynchronously, so typing latency is zero regardless of server round-trip time
- **Fault Tolerance via Eventual Consistency** — CRDT guarantees all peers converge to the same document state even after network partitions
- **Modifiability via Plugin Architecture** — CodeMirror 6's extension system allows language support to be added independently
- **Security via Session Isolation** — each document session is isolated by a unique room ID; no cross-session data leakage

### Design Patterns

- **Observer / Pub-Sub** — CRDT document changes trigger update events that all bound UI components observe and re-render from
- **Proxy Pattern** — the WebSocket sync server acts as a transparent relay, forwarding CRDT update messages without interpreting them
- **Strategy Pattern** — the conflict resolution strategy (CRDT merge) is encapsulated in Yjs, swappable independently of the editor UI

### Architecture Overview

```
Browser Client A                    Browser Client B
CodeMirror 6 + Yjs (CRDT)          CodeMirror 6 + Yjs (CRDT)
        |  WebSocket                    WebSocket  |
        +---------> Node.js Sync Server <----------+
                    (y-websocket, stateless)
                              |
                       Redis (CRDT state
                        persistence)
```

---

## 3. Expected Time to Build a Prototype

The prototype will implement three end-to-end nontrivial functionalities: (1) the CRDT conflict resolution layer using Yjs, (2) the WebSocket sync server for multi-client state propagation, and (3) the collaborative code editor frontend with live cursors and presence indicators.

| Phase | Duration | Owner(s) | Description |
|---|---|---|---|
| Research & Planning | 3 days | All | Study Yjs CRDT internals, y-websocket protocol, CodeMirror 6 bindings |
| Design | 3 days | 2 members | System architecture diagrams, CRDT document schema, WebSocket event design |
| Dev — CRDT + Sync Server | 5 days | 2 members | Yjs document setup, y-websocket server, multi-client sync testing |
| Dev — Editor Frontend | 5 days | 2 members | CodeMirror 6 + Yjs binding, cursor awareness UI, presence indicators |
| Dev — Persistence Layer | 3 days | 1 member | Redis-backed document state, session recovery on reconnect |
| Integration | 3 days | All | End-to-end multi-user testing, latency measurement, bug fixes |
| Testing & Refinement | 4 days | All | Concurrent edit stress tests, network partition simulation, UX polish |
| **Total** | **~4 weeks** | — | — |

---

## 4. Domain

**Primary Domain: Education / Enterprise.** SyncSpace directly addresses the collaborative coding gap in both online education and distributed software teams. In educational settings, instructors running live coding labs and students collaborating on assignments currently have no purpose-built tool — they cobble together screen sharing with a separate editor. In enterprise settings, pair programming and technical interviews are conducted over fragile screen-share sessions with no true co-editing.

The CRDT-based approach is architecturally significant because it inverts the traditional server-centric collaboration model. Rather than the server owning authoritative document state, the document is a distributed data structure that exists on every client simultaneously. This has broader implications for offline-first applications, edge computing scenarios, and any domain requiring collaborative data entry without central coordination.

---

## Appendix: Considered Alternatives & Reasons for Not Choosing Them

### A. SwiftShare — Distributed Microservices Ride-Sharing

SwiftShare proposes a decoupled microservices architecture using Kafka, an API Gateway, and WebSocket-based live driver location tracking. While architecturally sound and well-suited to a Smart Cities domain, it was set aside for two key reasons.

First, the integration surface area is wide. Four independent services — location tracking, matchmaking, trip management, and an API gateway — all need to be wired together correctly for any single flow to work end-to-end. This creates significant integration risk for a prototype that must be demonstrable within four weeks.

Second, the geospatial component (PostGIS, proximity queries) introduces a non-trivial domain-specific dependency that adds setup and debugging overhead beyond the core distributed systems concepts the course is assessing. Ride-sharing is also a well-trodden project topic, offering less novelty relative to the other candidates.

### B. PulseBoard — Real-Time Collaborative Analytics Dashboard

PulseBoard proposes a CQRS-based analytics dashboard with Redis Pub/Sub for multi-user state synchronization. It is a strong idea with low implementation risk and a clean architecture story, and was a serious contender.

It was ultimately not chosen because its core innovation — broadcasting filter and layout state across viewers — is conceptually simpler than it first appears. The CQRS pattern, while valuable, is less visually demonstrable in a prototype than the SyncSpace CRDT approach, where two people typing simultaneously in the same document is immediately compelling to an evaluator. SyncSpace also has a more distinct architectural identity (client-side distributed data structures vs. server-authoritative state), making it a stronger fit for a Software Engineering course that emphasizes architectural depth and novelty.
