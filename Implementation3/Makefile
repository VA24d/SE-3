# Implementation 3 — Pub-Sub + SSE (default port 8082; Implementation 1 uses 8080).

PYTHON ?= python3
VENV   := .venv
PIP    := $(VENV)/bin/pip
UV     := $(VENV)/bin/uvicorn

.PHONY: install start test-smoke help

help:
	@echo "Implementation 3 — HTTP Pub-Sub (POST + SSE) vs Impl 1 WebSocket Mediator"
	@echo "  make install     — venv + pip install -r requirements.txt"
	@echo "  make start       — server on 0.0.0.0:8082"
	@echo "  make test-smoke  — SSE publish round-trip check (port 8783)"

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

start:
	SYNCSPACE_PUBSUB_HOST=0.0.0.0 SYNCSPACE_PUBSUB_PORT=8082 \
	$(UV) server:app --host 0.0.0.0 --port 8082 --reload \
	  --app-dir src/server

test-smoke:
	$(VENV)/bin/python tests/sse_pubsub_smoke.py
