PINNED_NODE ?= /Users/tommasotessarolo/.hermes/node/bin/node

.PHONY: setup validate validate-pilot assess-w5 lint format-check test check

setup:
	uv sync --all-groups

validate:
	uv run metis-model1 validate-foundation

validate-pilot:
	uv run metis-model1 validate-pilot

assess-w5:
	uv run metis-model1 assess-w5

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

test:
	METIS_MODEL1_NODE="$(PINNED_NODE)" uv run pytest

check: validate validate-pilot lint format-check test
