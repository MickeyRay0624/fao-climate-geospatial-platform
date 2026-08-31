.PHONY: up down reset logs test geoserver

up:
	docker compose up --build

down:
	docker compose down

reset:
	docker compose down -v
	docker compose up --build

logs:
	docker compose logs -f api web

test:
	docker compose run --rm --no-deps api python -m pytest -q

geoserver:
	docker compose --profile geoserver up -d geoserver
