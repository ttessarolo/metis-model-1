PINNED_NODE ?= $(HOME)/.nvm/versions/node/v22.22.3/bin/node
PINNED_METIS_ROOT ?= /Users/tommasotessarolo/Developer/ares-matioska/metis
PINNED_ORACLE_NODE_MODULES ?= $(CURDIR)/artifacts/w5-xs/2026-08-24-delivery/metis-pinned/tooling/node_modules
TEST_WORKERS ?= 1

.PHONY: setup validate validate-pilot assess-experiment assess-w5 lint format-check test check

setup:
	uv sync --all-groups

validate:
	uv run metis-model1 validate-foundation

validate-pilot:
	uv run metis-model1 validate-pilot

assess-experiment:
	uv run metis-model1 assess-experiment

assess-w5:
	uv run metis-model1 assess-w5

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

test:
	uv run python -m metis_model1.test_harness \
		--metis-root "$(PINNED_METIS_ROOT)" \
		--oracle-node-modules "$(PINNED_ORACLE_NODE_MODULES)" \
		--node "$(PINNED_NODE)" \
		--workers "$(TEST_WORKERS)"

check: validate validate-pilot lint format-check test
