PYTHON ?= python3
VENV   := .venv
PIP    := $(VENV)/bin/pip
UV     := $(VENV)/bin/uvicorn

.PHONY: install start test-bench help

help:
	@echo "Implementation 2 — OT + Central Sequencer (port 8081)"
	@echo "  make install   — create venv and install dependencies"
	@echo "  make start     — start the OT server on 0.0.0.0:8081"
	@echo "  make test-bench — run NFR benchmark (starts server on port 8782)"

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

start:
	SYNCSPACE_OT_HOST=0.0.0.0 SYNCSPACE_OT_PORT=8081 \
	$(UV) server:app --host 0.0.0.0 --port 8081 --reload \
	  --app-dir src/server

test-bench:
	$(VENV)/bin/python tests/benchmark_nfr.py
