PY ?= python3
BIN = .venv/bin

.PHONY: setup run demo app test clean

setup:            ## virtual environment + pinned dependencies
	$(PY) -m venv .venv
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt

run:              ## full pipeline on data/raw/BPI_Challenge_2019.xes (a few minutes)
	$(BIN)/python scripts/run.py

demo:             ## pipeline on a small synthetic log (no download)
	$(BIN)/python scripts/run.py --synthetic

app:              ## dashboard on http://localhost:8501
	$(BIN)/streamlit run app.py

test:
	$(BIN)/python -m pytest -q

clean:
	rm -f data/*.duckdb data/*.parquet
