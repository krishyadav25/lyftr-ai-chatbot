.PHONY: help up down logs test

help:
	@echo "Available commands:"
	@echo "  make up     - Build and start backend (http://localhost:8000) and frontend (http://localhost:3000)"
	@echo "  make down   - Stop and remove service containers"
	@echo "  make logs   - Stream container logs"
	@echo "  make test   - Run backend pytest suite"

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

test:
	pytest backend/tests
