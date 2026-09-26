.PHONY: check lint type test fmt gap-report demo signals

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

test:  ## with line+branch coverage; fails under the floor in pyproject [tool.coverage.report]
	uv run pytest -q --cov --cov-report=term

gap-report:
	PYTHONPATH=. uv run python -m tests.gap.report > docs/gap-report.md.tmp && mv docs/gap-report.md.tmp docs/gap-report.md

demo:  ## seed the example app on SQLite and run the benchmark
	cd examples/clinic && rm -f clinic.sqlite3 && PYTHONPATH=. uv run python manage.py migrate -v 0 \
	  && PYTHONPATH=. uv run python manage.py seed_patients --rows $${ROWS:-100000} \
	  && PYTHONPATH=. uv run python manage.py benchmark --user alice --markdown

signals:  ## adoption signals: PyPI downloads, repo stats, the upstream issue, tolap-core version
	scripts/signals.sh
