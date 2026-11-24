# ==============================================================================
# Lyftr AI Chatbot - Makefile (SCAFFOLD)
# Note: Initial scaffold. Full Docker orchestration commands will be implemented
# in the containerization step.
# ==============================================================================

.PHONY: help up down test install clean

help:
	@echo "Available commands:"
	@echo "  make up       - Start backend (port 8000) and frontend (port 3000)"
	@echo "  make down     - Stop and remove all service containers"
	@echo "  make test     - Run backend test suite"
	@echo "  make install  - Install local development dependencies"

up:
	@echo "[Scaffold] 'make up' will start backend on http://localhost:8000 and frontend on http://localhost:3000"
	@echo "[Scaffold] Full Docker Compose startup will be wired in the containerization phase."

down:
	@echo "[Scaffold] 'make down' will stop running containers and release resources."

test:
	@echo "[Scaffold] Running backend pytest..."
	pytest backend/tests

install:
	@echo "[Scaffold] Installing dependencies..."
	pip install -r backend/requirements.txt
	cd frontend && npm install
