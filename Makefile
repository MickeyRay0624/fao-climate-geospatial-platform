.PHONY: up down logs test migrate seed geoserver

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api worker web

test:
	docker compose run --rm --no-deps api python -m pytest -q

migrate:
	docker compose run --rm migrate

seed:
	docker compose run --rm seed

geoserver:
	docker compose --profile geoserver up -d geoserver
