.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test check

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package with dev extras in editable mode.
	pip install -e ".[dev]"

lint:  ## Lint and verify formatting with ruff.
	ruff check .
	ruff format --check .

format:  ## Auto-format with ruff.
	ruff format .

typecheck:  ## Type-check with mypy.
	mypy

test:  ## Run the test suite.
	pytest

check: lint typecheck test  ## Run all quality gates.
