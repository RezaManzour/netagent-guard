PY ?= python
.PHONY: all install test eval demo tables
all: ; $(PY) run_all.py
install: ; $(PY) -m pip install -r requirements.txt
test: ; $(PY) -m pytest -q tests
eval: ; $(PY) run_all.py --skip-tests
demo: ; $(PY) -m uvicorn demo.app:app --port 8000
tables: ; $(PY) scripts/make_tables.py
