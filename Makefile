.PHONY: test lint build frontend

test:
	pytest tests/ -v --cov=bugfixer --cov-report=term-missing

lint:
	pytest tests/ -v

build:
	python -m build

frontend:
	cd frontend && npm run build && cp -r dist/* ../src/bugfixer/web/static/
