# Run from code/. Needs GNU make (Windows: winget install GnuWin32.Make, or skip make
# and use the commands in README.md). Recipes start with ">" instead of a tab.
.RECIPEPREFIX = >

ifeq ($(OS),Windows_NT)
PYTHON ?= py -3.12
PY     := .venv\Scripts\python
else
PYTHON ?= python3.12
PY     := .venv/bin/python
endif
CASE ?= ../samples/UC2-S01.json

.PHONY: help venv install lint format test test-unit test-integration check run eval eval-samples ui

help:
> @echo "make install        create .venv (Python 3.12) and install requirements"
> @echo "make check          lint + all tests"
> @echo "make run CASE=...   run one case (pauses for approval)"
> @echo "make eval           score tests/cases, writes tests/score.json"
> @echo "make eval-samples   score the pack's 5 samples"
> @echo "make ui             open the approval screen"

venv:
> $(PYTHON) -m venv .venv

install: venv
> $(PY) -m pip install -r requirements.txt

lint:
> $(PY) -m ruff check .
> $(PY) -m ruff format --check .

format:
> $(PY) -m ruff check --fix .
> $(PY) -m ruff format .

test:
> $(PY) -m pytest

test-unit:
> $(PY) -m pytest tests/unit

test-integration:
> $(PY) -m pytest tests/integration

check: lint test

run:
> $(PY) -m app run --case $(CASE) --out out/$(notdir $(CASE))

eval:
> $(PY) -m app eval --cases tests/cases

eval-samples:
> $(PY) -m app eval --cases ../samples

ui:
> $(PY) -m app.ui.web
