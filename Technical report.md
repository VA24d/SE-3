# Technical Report — SyncSpace (Project 3)

**Course:** S26CS6.401 — Software Engineering  
**Project:** SyncSpace — real-time collaborative code editor (CRDT + WebSocket relay)  
**Repository:** [SE 3](https://github.com/VA24d/SE-3) 

This report consolidates **design decisions**, **architecture**, **prototype implementation**, **quantitative analysis** against non-functional requirements, comparison to an **alternative architectural pattern**, **process reflections**, and **individual contributions**.

---

## 1. Executive summary

SyncSpace lets several users edit one shared source document in the browser with **low perceived latency**. Each browser holds a **Yjs** CRDT replica; edits apply locally first, then propagate as **binary update messages**. A **FastAPI** server does **not** merge or validate edits—it only **groups WebSockets by session** and **broadcasts** frames. **Awareness** (cursors, names) uses the same socket with a **one-byte prefix** so document and presence streams stay distinguishable. The prototype intentionally implements **one end-to-end capability**—real-time co-editing with presence—rather than the full SRS (e.g. multi-language highlighting beyond JavaScript, production TLS).

---

## 2. Requirements and architectural drivers

Detailed functional and non-functional requirements, subsystem decomposition, and rationale for architecturally significant requirements are in **`Task 1/SRS.md`** and **`Task 1/system.md`**.

**Drivers retained in the implementation:**

- **Local-first editing** (FR-CE-01) → Yjs on the client; no server round-trip before rendering a keystroke.
- **Deterministic conflict handling** (FR-CE-03) → CRDT instead of ad-hoc merging.
- **Live collaboration** (FR-CE-02, FR-PA-01) → WebSocket relay + Yjs Awareness + CodeMirror `y-codemirror.next`.
- **Simple operations** (deployment concern) → stateless relay; session routing only.

---

## 3. Architecture framework

### 3.1 Stakeholders (IEEE 42010)

Stakeholders, concerns, viewpoints, and views are documented in **`Task 2/Stakeholders.md`**.

### 3.2 Major design decisions (ADRs)

Four decisions are recorded with a **Nygard-style** template in **`Task 2/ADR/`**:

| ADR | Decision |
|-----|----------|
| ADR-001 | Yjs (CRDT) over operational transformation |
| ADR-002 | WebSocket over HTTP polling |
| ADR-003 | Web editor over VS Code extension |
| ADR-004 | Stateless relay over centralized document authority |

### 3.3 Tactics and patterns

- **Tactics (4–5):** **`Task 3/Arch tactics.md`** — aligned with the **as-built** prototype (relay forwards only; catch-up via **peers**, not server-side Y.Doc).
- **Patterns (2):** **`Task 3/Impl patterns.md`** — Observer (Yjs ↔ editor), Mediator (relay).

---

## 4. Implementation

### 4.1 Structure

| Component | Location | Role |
|-----------|----------|------|
| Relay + static host | `Implementation/src/server/server.py` | HTTP redirect to `/app/?session=…`, `StaticFiles` for client, `/ws/{session_id}` broadcast |
| Client | `Implementation/src/client/` | CodeMirror, Yjs, custom `SimpleProvider` for framing |
| Dependencies | `Implementation/requirements.txt` | FastAPI, Uvicorn, websockets (tests) |

### 4.2 Session and transport

- Visiting `/` issues a **307** redirect to `/app/?session=<id>` (short UUID fragment).
- Clients open `ws://<host>/ws/<session_id>` (or `wss` when deployed with TLS).
- **Binary protocol:** `0x00` + Yjs update, `0x01` + awareness update; **JSON** text is used only for `request_state` so new joiners can obtain a **full state** from existing peers (the server does not store document bytes).

### 4.3 Divergence from an “ideal” full system

The SRS mentions heartbeat timeouts, exponential backoff, and optional server-side state for diffs. The **prototype** uses:

- **Browser WebSocket** close events; on disconnect the client **reloads after 5 s** (simple recovery, not full backoff spec).
- **Peer-to-peer state exchange** for new members instead of a server-held Y.Doc.

These choices reduce server complexity and match **ADR-004**; they are called out so grading can distinguish **documentation vision** from **delivered prototype**. The full set of consciously accepted trade-offs (ephemeral sessions, reload-based recovery, trusted-client assumption, semantic conflict blindspot) and the explicit trust model are documented in **`Task 1/SRS.md` §§ 3.7–3.8**.

---

## 5. Architecture analysis: comparison to an alternative pattern

### 5.1 Chosen pattern (as implemented): CRDT + stateless relay

- **Correctness:** Convergence is delegated to **Yjs** on each replica; the relay cannot corrupt merge order because it does not merge.
- **Availability:** No single component must run **operational transformation** or hold authoritative document state.
- **Scalability of relay logic:** O(n) fan-out per message per session; acceptable for the **≤3 users** target.

### 5.2 Alternative pattern: operational transformation (OT) with central sequencer

A **single authoritative server** (or primary) receives all operations, **transforms** them against concurrent operations in a **total order**, then broadcasts **canonical** operations.

| Criterion | CRDT + stateless relay (SyncSpace) | OT + central server |
|-----------|-----------------------------------|---------------------|
| Server complexity | Low (forward only) | High (transform + ordering) |
| Offline / partition | CRDT designed for eventual merge | OT typically needs reconnect protocol & history |
| Latency perception | Excellent (local-first) | Depends on RTT to authority for confirmed ops |
| Consistency story | Eventual convergence (CRDT proof) | Immediate single ordering if server always up |

**Trade-off summary:** We traded a **powerful central coordinator** for **implementation simplicity** and **local-first UX**, which fits a semester prototype and NFR-P-02-style responsiveness. A production Google-Docs-scale system might combine CRDT/OT hybrids or richer server roles; that is out of scope here.

---

## 6. Quantified non-functional properties (prototype)

Measurements support **at least two** NFR families from **`Task 1/SRS.md`**: **responsiveness / latency** (NFR-P-01 area) and **throughput** as a proxy for **scalability headroom** under burst traffic (NFR-SC / performance).

**Method:** Script `Implementation/tests/benchmark_nfr.py` starts **Uvicorn** on `127.0.0.1:8777`, samples **40** HTTP redirects and **40** WebSocket relay round-trips (two clients in-session), then **400** relay round-trips for throughput. **Environment:** single developer machine (local loopback); numbers **vary by hardware and OS**.

**Sample run (2026-04-23, Apple Silicon class laptop, loopback):**

| Metric | Mean | Median | Min | Max |
|--------|------|--------|-----|-----|
| HTTP `GET /` (redirect) | **0.85 ms** | 0.54 ms | 0.34 ms | 10.77 ms |
| WebSocket relay one-hop (5-byte frame) | **0.20 ms** | 0.18 ms | 0.16 ms | 0.28 ms |

**Throughput (same run):** **~7,170** relayed messages/s for **129-byte** binary frames (400 round-trips measured end-to-end between two clients).

**Interpretation:**

1. **Latency (NFR-P-01 context):** On localhost, relay contribution is **well under 1 s** and **well under 500 ms**—the dominant factor in real deployments becomes **WAN RTT**, not Python fan-out for small sessions.
2. **Throughput:** The relay sustains **thousands of small messages per second** between two peers, indicating headroom for typing bursts and awareness updates for **three** users before the prototype becomes network-bound.

Re-run the script before submission if you want **your** machine’s figures in an appendix.

---

## 7. Reflections and lessons learned

- **Framing matters:** Mixing Yjs updates and awareness on one WebSocket required an explicit **prefix byte**; forgetting it on some code paths broke convergence—good lesson in **protocol discipline** for “simple” relays.
- **Docs vs. code:** Early docs assumed **server-side** state vectors and app-level heartbeats; the shipped prototype is **leaner**. Updating **tactics** and **subsystem** descriptions to match reality avoided misleading evaluators.
- **Scope control:** Delivering **one strong E2E flow** (co-edit + presence) satisfied the prototype bar without implementing every SRS “Should” item.
- **Testing:** Automated **smoke** (`ws_relay_smoke.py`) and **benchmarks** (`benchmark_nfr.py`) made regressions in the relay obvious and gave concrete numbers for the report.

---

## 8. Individual contributions

*Complete this table before submission. Only one member uploads to Moodle, but **everyone** should appear here.*

| Team member | Primary areas | Specific contributions |
|-------------|---------------|------------------------|
| *Name 1* | *e.g. relay, DevOps* | *e.g. FastAPI server, smoke tests* |
| *Name 2* | *e.g. client, Yjs* | *e.g. SimpleProvider, CodeMirror integration* |
| *Name 3* | *e.g. documentation* | *e.g. SRS, ADRs, technical report* |

---

## 9. References to repository artifacts

- Requirements: `Task 1/SRS.md`, `Task 1/system.md`
- Stakeholders: `Task 2/Stakeholders.md`
- ADRs: `Task 2/ADR/`
- Tactics / patterns: `Task 3/Arch tactics.md`, `Task 3/Impl patterns.md`
- Code: `Implementation/src/`
- Setup: **`README.md`**
