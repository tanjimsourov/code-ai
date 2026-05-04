PYTHON ?= python

install:
	$(PYTHON) -m pip install -U pip
	$(PYTHON) -m pip install -e .[dev,postgres,channels_redis]

dev:
	$(PYTHON) manage.py runserver --settings=config.settings.local

test:
	pytest -q

check:
	$(PYTHON) manage.py check --settings=config.settings.local --fail-level WARNING

migrate:
	$(PYTHON) manage.py migrate --settings=config.settings.local

makemigrations-check:
	$(PYTHON) manage.py makemigrations --settings=config.settings.local --check --dry-run

smoke:
	$(PYTHON) manage.py code_editor_smoke_check --settings=config.settings.local

validate:
	$(PYTHON) manage.py code_editor_validate_install --settings=config.settings.local

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
