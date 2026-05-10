.PHONY: pg-up pg-down pg-logs install test test-fast lint type coverage format clean

pg-up:
	docker compose up -d pg

pg-down:
	docker compose down

pg-logs:
	docker compose logs -f pg

install:
	uv sync --locked --dev

test:
	uv run pytest --cov=src/scraper --cov-fail-under=85

test-fast:
	uv run pytest -x -q -m "not network and not slow"

lint:
	uv run ruff check .

type:
	uv run mypy src/scraper

coverage:
	uv run pytest --cov=src/scraper --cov-report=html --cov-fail-under=85

format:
	uv run ruff format .

clean:
	rm -rf .venv dist __pycache__ .pytest_cache htmlcov .coverage
