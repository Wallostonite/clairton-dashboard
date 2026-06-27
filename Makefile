.PHONY: help setup etl run test lint clean

PY ?= python

help:
	@echo "make setup   - install runtime + dev dependencies"
	@echo "make etl     - run the ETL pipeline (raw -> processed parquet)"
	@echo "make run     - launch the Streamlit dashboard"
	@echo "make test    - run the test suite"
	@echo "make clean   - remove processed artifacts and caches"

setup:
	$(PY) -m pip install -r requirements-dev.txt

etl:
	$(PY) etl.py

run:
	$(PY) -m streamlit run app.py

test:
	$(PY) -m pytest -q

clean:
	rm -f data/processed/clean_data.parquet data/processed/data_quality.json
	rm -rf __pycache__ .pytest_cache tests/__pycache__
