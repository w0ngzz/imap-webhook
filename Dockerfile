FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md config.example.json docker-entrypoint.sh ./
COPY imap_gotify ./imap_gotify

RUN pip install --no-cache-dir .

RUN mkdir -p /data \
    && chmod +x /app/docker-entrypoint.sh

VOLUME ["/data"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "imap_gotify", "-c", "/data/config.json", "--web-enable", "--web-host", "0.0.0.0", "--web-port", "8080"]
