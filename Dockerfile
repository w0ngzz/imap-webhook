FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY imap_gotify ./imap_gotify

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/state /app/logs \
    && chown -R appuser:appuser /app

USER appuser

VOLUME ["/app/state", "/app/logs"]

CMD ["python", "-m", "imap_gotify", "-c", "/app/config.json"]
