.PHONY: install demo serve check report site docker
install:
	uv sync --frozen --extra dev
demo:
	uv run tokenledger demo
serve:
	uv run tokenledger serve
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -q
report:
	uv run tokenledger evaluate --output reports/evaluation.json
	uv run tokenledger export --output reports/demo-report.json
site:
	uv run python scripts/build_site.py
docker:
	docker compose up --build
