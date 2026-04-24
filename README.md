# SyncSpace

SyncSpace is a **real-time collaborative code editor** prototype. Multiple users join a shared **session** in the browser, edit the same document with **CodeMirror 6**, and see each other’s cursors and names. The shared text is synchronized with **Yjs** (a CRDT); a small **Python** server only **relays** WebSocket messages and does not interpret document content.

**Course:** S26CS6.401 — Software Engineering (Project 3)

**Repository (replace if you fork):** [SE 3](https://github.com/VA24d/SE-3)

---

## Repository layout

| Path | Purpose |
|------|---------|
| `Implementation/src/server/` | FastAPI + Uvicorn relay, static mount for the web client |
| `Implementation/src/client/` | HTML/CSS/JS editor UI (ES modules + import maps) |
| `Implementation/doc/arch/` | ADRs aligned with the implementation |
| `Implementation/requirements.txt` | Python dependencies |
| `Implementation/Makefile` | Cross-platform tasks (`make install`, `make start`, tests) |
| `Implementation/start.sh` | One-command start on macOS / Linux (LAN + printed URLs) |
| `Implementation/start.ps1` | One-command start on Windows (PowerShell) |
| `Implementation/tests/` | Smoke and latency/throughput checks |
| `Task 1/` | Requirements (SRS) and subsystem overview |
| `Task 2/` | Stakeholders (IEEE 42010) and ADRs |
| `Task 3/` | Architectural tactics and design patterns |
| `Technical report.md` | Consolidated report for submission |

---

## Prerequisites

- **Python 3.11+** (tested with 3.13)
- A modern **desktop browser** (Chrome, Firefox, Edge, or Safari)

---

## Setup

From the repository root:

```bash
cd Implementation
python3 -m venv .venv
```

**Windows (PowerShell):**

```powershell
cd Implementation
python3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux:**

```bash
cd Implementation
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Run the application

### Make (Windows, macOS, Linux)

Requires **GNU Make** and **Python** on the `PATH` (`python` on Windows, `python3` on macOS/Linux).

From **`Implementation/`** after `make install` (or manual venv + `pip install -r requirements.txt`):

```bash
make install
make start
```

`make start` listens on **all interfaces** (`SYNCSPACE_HOST=0.0.0.0`) and prints **127.0.0.1** and **LAN** URLs. Override port: `make start SYNCSPACE_PORT=9000`. Localhost only: `make start SYNCSPACE_HOST=127.0.0.1`.

### Shell scripts

From **`Implementation/`**:

**macOS / Linux:** `./start.sh` (after `chmod +x start.sh` if needed)

**Windows (PowerShell):** `.\start.ps1`

### Manual run

The server must be started with working directory `Implementation/src/server` so static files resolve to `../client`.

**macOS / Linux:**

```bash
cd Implementation/src/server
../../.venv/bin/python server.py
```

**Windows (PowerShell):**

```powershell
cd Implementation\src\server
..\..\.venv\Scripts\python.exe server.py
```

Then open **[http://127.0.0.1:8080/](http://127.0.0.1:8080/)**. You are redirected to `/app/?session=…`. Open the same URL (or use **Share link**) in another window to collaborate in the same session.

For a **two-system** test, the person running the server can share the session URL shown by the **Share link** button or by `GET /api/share-link?session=...`. On the other machine, run the benchmark against that URL to print live relay numbers:

```bash
cd Implementation
python tests/benchmark_nfr.py --session-url "http://HOST:PORT/app/?session=SESSION_ID"
```

---

## Automated checks

With the venv activated and dependencies installed:

```bash
cd Implementation
python tests/ws_relay_smoke.py
python tests/benchmark_nfr.py
```

`ws_relay_smoke.py` starts a temporary server and checks HTTP redirect plus WebSocket relaying. `benchmark_nfr.py` prints sample **latency** and **throughput** numbers (documented in `Technical report.md`).

If you want numbers from a running server on another machine, pass its shared session URL with `--session-url` as shown above.

---

## Documentation for grading

- Requirements and subsystems: `Task 1/`
- Architecture (stakeholders, ADRs): `Task 2/`
- Tactics and patterns: `Task 3/`
- Full narrative, analysis, contributions, and GitHub link for Moodle: **`Technical report.md`**

---

## License / academic use

Submitted as coursework; adapt reuse policies to your institution’s rules.
