# Installation

## Requirements

- Python 3.11+
- pip
- PostgreSQL (staging/production)
- Redis (recommended)

## Steps

1. Install dependencies:
   - `python -m pip install -e .[dev,postgres,channels_redis]`
2. Create env:
   - `cp .env.example .env`
3. Run migrations:
   - `python manage.py migrate --settings=config.settings.local --noinput`
4. Create admin user:
   - `python manage.py createsuperuser --settings=config.settings.local`
5. Start development server:
   - `python manage.py runserver --settings=config.settings.local`

## ASGI/WSGI

- Gunicorn (WSGI): `gunicorn -c gunicorn.conf.py config.wsgi:application`
- Daphne (ASGI): `daphne -b 0.0.0.0 -p 8001 config.asgi:application`
