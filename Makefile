# Data layer targets (milestone M1). Analysis, report and `all` are added by the other milestones.
PY ?= python

.PHONY: data validate test explore report-data

data:
	$(PY) src/fetch.py
	$(PY) src/panel.py

validate:
	$(PY) src/validate.py

test:
	$(PY) -m pytest tests/

explore:
	$(PY) src/explore.py

report-data:
	$(PY) src/data_report.py
