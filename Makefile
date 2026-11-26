# Route Card Generator — V&V shortcuts

.PHONY: test-vnv test-e2e report-vnv vnv bandit-vnv

test-vnv:
	cd backend && .venv/Scripts/python.exe -m pytest tests/vnv -q --tb=short --junitxml=../docs/vnv/artifacts/pytest-vnv.xml

test-e2e:
	cd frontend && npm run test:e2e

report-vnv:
	cd backend && .venv/Scripts/python.exe ../docs/vnv/run_vnv.py

vnv: report-vnv

bandit-vnv:
	cd backend && .venv/Scripts/python.exe -m bandit -r app -ll -ii -f json -o ../docs/vnv/artifacts/bandit-vnv.json
