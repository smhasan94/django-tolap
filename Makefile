.PHONY: check lint type test fmt gap-report

check: lint type test

lint:
	uv run ruff check .
	uv run ruff format --check .
	PYTHONPATH=. uv run python -m django makemigrations --check --dry-run --settings tests.settings django_tolap

fmt:
	uv run ruff format .
	uv run ruff check --fix .

type:
	uv run mypy

test:
	uv run pytest -q

gap-report:
	PYTHONPATH=. uv run python -m tests.gap.report > docs/gap-report.md.tmp && mv docs/gap-report.md.tmp docs/gap-report.md
