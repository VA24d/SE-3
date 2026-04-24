# SyncSpace — cross-platform tasks (needs GNU Make + Python).
#
# Windows: install "make" (e.g. choco install make, Scoop, or Git Bash / WSL).
# From this directory:  make install   &&   make start
#
# macOS / Linux: GNU Make is standard.

.DEFAULT_GOAL := help

HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

ifeq ($(OS),Windows_NT)
  VENV_PY   := $(HERE)/.venv/Scripts/python.exe
  VENV_PIP  := $(HERE)/.venv/Scripts/pip.exe
  SYSTEM_PY := python
else
  VENV_PY   := $(HERE)/.venv/bin/python
  VENV_PIP  := $(HERE)/.venv/bin/pip
  SYSTEM_PY := python3
endif

REQ := $(HERE)/requirements.txt

.PHONY: help venv install start run test-smoke test-bench clean-venv

help:
	@echo "SyncSpace Makefile"
	@echo ""
	@echo "  make install     Create .venv (if missing) and pip install -r requirements.txt"
	@echo "  make start       Print URLs and run server (0.0.0.0:8080 — LAN + localhost)"
	@echo "  make run         Same as start"
	@echo "  make test-smoke  WebSocket relay smoke test (temporary server on 8765)"
	@echo "  make test-bench  Local latency / throughput sample"
	@echo "  make clean-venv  Remove .venv (Python — works on Win/Mac/Linux)"
	@echo ""
	@echo "Override port:  make start SYNCSPACE_PORT=9000"
	@echo "This folder: $(HERE)"

$(VENV_PY):
	$(SYSTEM_PY) -m venv "$(HERE)/.venv"

venv: $(VENV_PY)
	@echo "venv ready: $(VENV_PY)"

install: $(VENV_PY)
	"$(VENV_PIP)" install -r "$(REQ)"

start run: $(VENV_PY)
ifeq ($(OS),Windows_NT)
	powershell -NoProfile -ExecutionPolicy Bypass -File "$(HERE)/start.ps1"
else
	SYNCSPACE_HOST="$(SYNCSPACE_HOST)" SYNCSPACE_PORT="$(SYNCSPACE_PORT)" bash "$(HERE)/start.sh"
endif

test-smoke: $(VENV_PY)
	"$(VENV_PY)" "$(HERE)/tests/ws_relay_smoke.py"

test-bench: $(VENV_PY)
	"$(VENV_PY)" "$(HERE)/tests/benchmark_nfr.py"

clean-venv:
	@"$(SYSTEM_PY)" -c "import shutil, pathlib; p = pathlib.Path(r'$(HERE)') / '.venv'; shutil.rmtree(p, ignore_errors=True); print('removed', p)"
