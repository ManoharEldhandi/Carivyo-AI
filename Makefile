.PHONY: install setup-enhancv dev backend frontend test test-backend test-frontend build check

PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
PYPI_INDEX ?= https://pypi.org/simple

install:
	$(PYTHON) -c 'import sys; assert sys.version_info >= (3, 11), "Carivyo requires Python 3.11+"'
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install --index-url "$(PYPI_INDEX)" --upgrade pip setuptools wheel
	.venv/bin/python -m pip install --index-url "$(PYPI_INDEX)" -e "backend[dev]"
	cd frontend && npm ci

setup-enhancv:
	cd frontend && npx playwright install chromium

dev:
	./scripts/dev.sh

backend:
	.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8420 --reload

frontend:
	cd frontend && npm run dev -- --host 127.0.0.1 --strictPort

test: test-backend test-frontend

test-backend:
	.venv/bin/pytest backend/tests

test-frontend:
	cd frontend && npm test -- --run

build:
	cd frontend && npm run build

check: test build
	.venv/bin/python -m pip check
	cd frontend && npm audit --omit=dev
