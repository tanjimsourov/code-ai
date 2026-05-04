FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 10001 appuser
WORKDIR /app

COPY pyproject.toml README.md /app/
COPY apps /app/apps
COPY config /app/config
COPY code_editor /app/code_editor
COPY manage.py /app/manage.py

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .[postgres,channels_redis]

RUN mkdir -p /app/staticfiles /app/media /app/var && chown -R appuser:appuser /app

USER appuser
ENV DJANGO_SETTINGS_MODULE=config.settings.production

CMD ["gunicorn", "-c", "gunicorn.conf.py", "config.wsgi:application"]
