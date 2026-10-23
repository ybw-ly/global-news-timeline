FROM python:3.12-slim

LABEL org.opencontainers.image.title="Meridian Global News Timeline"
LABEL org.opencontainers.image.description="Local-first global news timeline with region/source/language/type filters"

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    HOST=0.0.0.0 \
    PORT=8765 \
    NEWS_DB=/app/data/news.db

WORKDIR /app

COPY server ./server
COPY web ./web
COPY config ./config
COPY scripts ./scripts
COPY tests ./tests
COPY data/geo ./data/geo

RUN mkdir -p /app/data

EXPOSE 8765
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)" || exit 1

CMD ["python", "server/app.py"]
